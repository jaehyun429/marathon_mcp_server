# marathon_server.py
# type: ignore
from fastmcp import FastMCP
import httpx
from bs4 import BeautifulSoup
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import sys

mcp = FastMCP("marathon-crawler")

# 간단한 메모리 캐시
_cache = {
    'data': None,
    'timestamp': None,
    'ttl': 3600  # 1시간 캐시
}

async def fetch_detail(client: httpx.AsyncClient, detail_url: str, base_domain: str) -> Optional[dict]:
    """정적 단일 마라톤 상세 정보 가져오기"""
    try:
        full_url = base_domain + detail_url if not detail_url.startswith('http') else detail_url
        response = await client.get(full_url, timeout= 15.0)
        response.raise_for_status()

        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        script_tag = soup.find('script', {'id': '__NEXT_DATA__'})
        
        if script_tag:
            json_data = json.loads(script_tag.string)
            race_detail = json_data.get('props', {}).get('pageProps', {}).get('raceDetail', {})
            
            if race_detail:
                return {
                    '마라톤명': race_detail.get('raceName', ''),
                    '트랙': race_detail.get('raceTypeList', '').split(',') if race_detail.get('raceTypeList') else [],
                    '지역': race_detail.get('region', ''),
                    '장소': race_detail.get('place', ''),
                    '날짜': race_detail.get('raceDate', ''),
                    '집결시간': race_detail.get('raceStart', ''),
                    '접수기간': {
                        '시작일': race_detail.get('applicationStartDate', ''),
                        '종료일': race_detail.get('applicationEndDate', '')
                    },
                    '문의처': {
                        '이메일': race_detail.get('email', ''),
                        '전화번호': race_detail.get('phone', '')
                    },
                    '주최': race_detail.get('host', ''),
                    '홈페이지': race_detail.get('homepageUrl', ''),
                    '소개': race_detail.get('intro', ''),
                    '상세URL': detail_url
                }
    except Exception as e:
        print(f"Error fetching {detail_url}: {e}", file=sys.stderr)
        return None

def is_accepting_applications(marathon: dict) -> bool:
    """접수 가능 여부 확인"""
    try:
        end_date_str = marathon.get('접수기간', {}).get('종료일', '')
        if not end_date_str:
            return False
        
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        return end_date >= today
    except:
        return False

def format_marathon_info(marathon: dict, include_contact: bool = True) -> str:
    """마라톤 정보를 보기 좋게 포맷팅"""
    lines = []
    
    # 기본 정보
    lines.append(f"🏃 {marathon.get('마라톤명', '정보 없음')}")
    
    # 트랙 정보
    tracks = marathon.get('트랙', [])
    if tracks:
        tracks_str = ', '.join([t.strip() for t in tracks if t.strip()])
        lines.append(f"📏 트랙: {tracks_str}")
    
    # 날짜 및 장소
    race_date = marathon.get('날짜', '')
    if race_date:
        lines.append(f"📅 날짜: {race_date}")
    
    gathering_time = marathon.get('집결시간', '')
    if gathering_time:
        lines.append(f"⏰ {gathering_time}")
    
    location = marathon.get('지역', '')
    place = marathon.get('장소', '')
    if location or place:
        loc_str = f"{location} - {place}" if location and place else (location or place)
        lines.append(f"📍 장소: {loc_str}")
    
    # 접수 기간
    app_period = marathon.get('접수기간', {})
    start_date = app_period.get('시작일', '')
    end_date = app_period.get('종료일', '')
    
    if start_date and end_date:
        is_open = is_accepting_applications(marathon)
        status = "✅ 접수 중" if is_open else "❌ 접수 마감"
        lines.append(f"📝 접수기간: {start_date} ~ {end_date} ({status})")
    elif end_date:
        is_open = is_accepting_applications(marathon)
        status = "✅ 접수 중" if is_open else "❌ 접수 마감"
        lines.append(f"📝 접수 마감: {end_date} ({status})")
    
    # 문의처 (요청 시에만)
    if include_contact:
        contact = marathon.get('문의처', {})
        email = contact.get('이메일', '')
        phone = contact.get('전화번호', '')
        
        if email or phone:
            lines.append("📞 문의처:")
            if email:
                lines.append(f"   ✉️ {email}")
            if phone:
                lines.append(f"   📱 {phone}")
    
    # 주최
    host = marathon.get('주최', '')
    if host:
        lines.append(f"🏢 주최: {host}")
    
    # 홈페이지
    homepage = marathon.get('홈페이지', '')
    if homepage:
        lines.append(f"🔗 {homepage}")
    
    # 소개
    intro = marathon.get('소개', '')
    if intro and len(intro) > 10:
        intro_short = intro[:100] + '...' if len(intro) > 100 else intro
        lines.append(f"ℹ️ {intro_short}")
    
    return '\n'.join(lines)

async def crawl_marathons_fast(base_url: str, base_domain: str, max_concurrent: int = 10) -> list:
    """병렬 처리로 빠르게 크롤링"""
    all_marathons = []
    
    async with httpx.AsyncClient() as client:
        try:
            # 1. 목록 페이지 HTML 정적 요청
            response = await client.get(base_url, timeout=30.0)
            response.raise_for_status()
            html = response.text
            
            soup = BeautifulSoup(html, 'html.parser')
            marathon_links = soup.find_all('a', class_='MuiLink-root')
            
            detail_urls = []
            for link in marathon_links:
                href = link.get('href', '')
                if href and '/raceDetail/' in href and href not in detail_urls:
                    detail_urls.append(href)
            
            if not detail_urls:
                print("경고: 상세 페이지 링크를 찾지 못했습니다. (사이트 구조 변경 가능성)", file=sys.stderr)
                return []
            
            # 2. 병렬로 상세 페이지 크롤링
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def fetch_with_semaphore(url):
                async with semaphore:
                    result = await fetch_detail(client, url, base_domain)
                    return result
            
            tasks = [fetch_with_semaphore(url) for url in detail_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_marathons = [r for r in results if r and not isinstance(r, Exception)]
            
        except httpx.HTTPStatusError as e:
            print(f"HTTP 오류 발생 : {e.response.status_code} - {e.request.url}", file=sys.stderr)
        except Exception as e:
            print(f"크롤링 중 알 수 없는 오류 발생 : {e}", file=sys.stderr)
    
    return all_marathons

def is_cache_valid() -> bool:
    """캐시가 유효한지 확인"""
    if _cache['data'] is None or _cache['timestamp'] is None:
        return False
    
    elapsed = datetime.now() - _cache['timestamp']
    return elapsed.total_seconds() < _cache['ttl']

@mcp.tool()
async def crawl_korean_marathons(
    base_url: str = "https://marathongo.co.kr/races",
    base_domain: str = "https://marathongo.co.kr",
    region_filter: str = "",
    date_filter: str = "",
    only_accepting: bool = False,
    use_cache: bool = True
) -> str:
    """
    한국의 마라톤 대회 정보를 크롤링하여 상세 정보를 가져옵니다.
    
    병렬 처리로 빠르게 크롤링하며, 1시간 동안 결과를 캐싱합니다.
    
    Args:
        base_url: 크롤링할 마라톤 목록 페이지의 URL (기본값: 마라톤GO)
        base_domain: 웹사이트의 기본 도메인 URL
        region_filter: 특정 지역 필터링 (예: '서울', '경기', '부산'). 비워두면 전체 검색
        date_filter: 특정 날짜/월 필터링 (예: '2025-11', '2025-11-15'). 비워두면 전체 검색
        only_accepting: True일 경우 현재 접수 가능한 대회만 반환 (기본값: False)
        use_cache: 캐시 사용 여부 (기본값: True)
    
    Returns:
        포맷팅된 마라톤 정보 목록
        
    수집 정보:
        - 마라톤명, 트랙 종류 (10km, 5km 등)
        - 개최 지역 및 장소, 대회 날짜, 집결 시간
        - 접수 기간 (시작일, 종료일) 및 접수 가능 여부
        - 문의처 (이메일, 전화번호)
        - 주최 기관, 홈페이지, 대회 소개
    
    사용 예시:
        - "2025년 11월에 있는 마라톤 알려줘"
        - "서울에서 하는 마라톤 찾아줘"
        - "지금 신청할 수 있는 마라톤 있어?"
        - "이번 주말 마라톤 대회 있어?"
    """
    
    # 캐시 확인
    if use_cache and is_cache_valid():
        results = _cache['data']
    else:
        print("Fetching new data", file=sys.stderr)
        results = await crawl_marathons_fast(base_url, base_domain, max_concurrent=10)
        if results:
            _cache['data'] = results
            _cache['timestamp'] = datetime.now()
            print(f"데이터 {len(results)}개 로드 및 캐시 저장", file=sys.stderr)
        else:
            print("Data fetch failed", file=sys.stderr)
        
    # 필터링 적용
    filtered_results = results
    
    if region_filter:
        filtered_results = [m for m in filtered_results if region_filter in m.get('지역', '')]
    
    if date_filter:
        filtered_results = [m for m in filtered_results if date_filter in m.get('날짜', '')]
    
    if only_accepting:
        filtered_results = [m for m in filtered_results if is_accepting_applications(m)]
    
    # 날짜순 정렬
    filtered_results.sort(key=lambda x: x.get('날짜', '9999-99-99'))
    
    # 결과 포맷팅
    if not filtered_results:
        message = "현재 접수 가능한 마라톤이 없습니다." if only_accepting else "검색 조건에 맞는 마라톤을 찾지 못했습니다."
        return f"❌ {message}\n\n💡 팁: 다른 지역이나 날짜로 검색해보세요."
    
    # 마라톤 정보 포맷팅
    formatted_list = []
    for i, marathon in enumerate(filtered_results, 1):
        formatted = format_marathon_info(marathon, include_contact=True)
        formatted_list.append(f"\n{'='*50}\n[{i}] {formatted}\n{'='*50}")
    
    header = f"✅ 총 {len(filtered_results)}개의 마라톤을 찾았습니다"
    if only_accepting:
        header += " (접수 가능한 대회만)"
    header += "\n"
    
    footer = "\n\n💡 특정 마라톤의 상세 정보가 필요하시면 말씀해주세요!"
    
    return header + '\n'.join(formatted_list) + footer


@mcp.tool()
async def clear_marathon_cache() -> str:
    """
    마라톤 데이터 캐시를 삭제합니다.
    최신 정보가 필요할 때 사용하세요.
    
    Returns:
        캐시 삭제 결과 메시지
    """
    _cache['data'] = None
    _cache['timestamp'] = None
    
    return "✅ 캐시가 삭제되었습니다. 다음 검색 시 최신 데이터를 가져옵니다."


if __name__ == "__main__":
    mcp.run()
