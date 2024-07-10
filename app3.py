import streamlit as st
from googleapiclient.discovery import build
import re
from googleapiclient.errors import HttpError
import pickle
import os
from datetime import datetime, timedelta
import hmac
import toml
import glob

# YouTube Data APIのAPIキー
API_KEY = 'AIzaSyDM2F_A0kreCYAONjzGq4RBvKTvOU3aII4'

# YouTubeカテゴリーリスト
YOUTUBE_CATEGORIES = [
    "すべて", "音楽", "ニュース", "ゲーム", "ライブ", "野球", "観光", "料理", "自然", "最近アップロードされた動画", "新しい動画の発見"
]

# ローカル環境用のシークレット読み取り
def get_local_secret(key, default=None):
    try:
        with open('.streamlit/secrets.toml', 'r') as f:
            secrets = toml.load(f)
        return secrets['general'][key]
    except Exception as e:
        return default

# パスワードを取得
def get_password():
    try:
        return st.secrets['general']['password']
    except KeyError:
        return get_local_secret('password', 'default_password')

# APIリクエスト数のカウンター
if 'api_requests' not in st.session_state:
    st.session_state.api_requests = 0

# スポンサー情報を抽出するための正規表現パターン
sponsor_patterns = [
    r'(?:提供|スポンサー|協賛|PR|広告|サポート)[:：]\s*([^、\n]+)',
    r'([\w\s]+)の提供でお送りします',
    r'本動画は([\w\s]+)とのタイアップ',
    r'([\w\s]+)様のご協力のもと',
    r'sponsored by\s+([\w\s]+)',
    r'本動画は([\w\s]+)の広告を含みます',
    r'番組スポンサー[:：]?\s*([^\n]+)',
    r'([\w\s]+)様による番組提供',
    r'提供：([\w\s]+)',
    r'【番組スポンサー】\s*([^\n]+)',
]

# 除外するパターン（音楽関連の提供を含む）
exclude_patterns = [
    r'動画提供',
    r'楽曲提供',
    r'音楽提供',
    r'BGM提供',
    r'Production Music by',
    r'epidemicsound\.com',
    r'PIXTA',
    r'甘茶の音楽工房',
    r'musmus\.main\.jp',
    r'NoCopyrightSounds',
    r'Music, Artlist License',
    r'株式会社アイリング',
    r'楽曲提供：.*',  # 楽曲提供で始まる全ての文字列を除外
]

def extract_sponsors(description):
    sponsors = []
    for pattern in sponsor_patterns:
        matches = re.findall(pattern, description, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            if isinstance(match, tuple):
                sponsors.extend(match)
            else:
                sponsors.append(match)
    
    # 除外パターンに一致するスポンサーを除外
    sponsors = [sponsor.strip() for sponsor in sponsors if sponsor.strip() and not any(re.search(ep, sponsor, re.IGNORECASE) for ep in exclude_patterns)]
    
    # URLのみの場合や、"Music"のみの場合は除外
    sponsors = [sponsor for sponsor in sponsors if not sponsor.startswith('http') and not sponsor.startswith('www.') and sponsor.lower() != 'music']
    
    return sponsors

def clear_cache():
    cache_files = glob.glob("cache_*.pkl")
    for file in cache_files:
        os.remove(file)
    st.success("キャッシュがクリアされました。")

def get_video_details(api_key, video_ids):
    youtube = build('youtube', 'v3', developerKey=api_key)
    video_details = []
    
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        try:
            details_response = youtube.videos().list(
                id=','.join(chunk),
                part='snippet,statistics,contentDetails'
            ).execute()
            st.session_state.api_requests += 1

            for item in details_response.get('items', []):
                description = item['snippet']['description']
                title = item['snippet']['title']
                sponsors_found = extract_sponsors(description)
                
                video_details.append({
                    'title': title,
                    'viewCount': item['statistics'].get('viewCount', 'N/A'),
                    'publishedAt': item['snippet']['publishedAt'],
                    'description': description,
                    'thumbnailUrl': item['snippet']['thumbnails']['high']['url'],
                    'url': f"https://www.youtube.com/watch?v={item['id']}",
                    'sponsors': sponsors_found
                })
        except HttpError as e:
            st.error(f"動画情報の取得中にエラーが発生しました: {str(e)}")
    
    return video_details

def search_videos_with_paging(api_key, query, max_results_per_page=50, total_results=200, order='relevance', video_category=''):
    cache_file = f"cache_{query.replace(' ', '_')}_{order}_{video_category}.pkl"
    if os.path.exists(cache_file) and (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))).days < 1:
        with open(cache_file, 'rb') as f:
            return pickle.load(f)

    youtube = build('youtube', 'v3', developerKey=api_key)
    video_ids = []
    next_page_token = None

    progress_text = "検索中..."
    progress_bar = st.progress(0)

    while len(video_ids) < total_results:
        try:
            search_params = {
                'q': query,
                'part': 'snippet',
                'type': 'video',
                'maxResults': max_results_per_page,
                'order': order,
                'pageToken': next_page_token
            }
            if video_category:
                search_params['videoCategoryId'] = video_category

            search_response = youtube.search().list(**search_params).execute()
            st.session_state.api_requests += 1

            video_ids.extend([item['id']['videoId'] for item in search_response.get('items', [])])
            next_page_token = search_response.get('nextPageToken', None)

            progress = min(len(video_ids) / total_results, 1.0)
            progress_bar.progress(progress, text=progress_text)

            if next_page_token is None:
                break
        except HttpError as e:
            st.error(f"動画の検索中にエラーが発生しました: {str(e)}")
            break

    progress_bar.empty()
    results = get_video_details(api_key, video_ids[:total_results])
    
    with open(cache_file, 'wb') as f:
        pickle.dump(results, f)
    
    return results

def get_category_id(youtube, category_name):
    try:
        categories = youtube.videoCategories().list(part='snippet', regionCode='JP').execute()
        for category in categories['items']:
            if category['snippet']['title'].lower() == category_name.lower():
                return category['id']
    except HttpError as e:
        st.error(f"カテゴリーIDの取得中にエラーが発生しました: {str(e)}")
    return None

def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if hmac.compare_digest(st.session_state["password"], get_password()):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "パスワードを入力してください", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input(
            "パスワードを入力してください", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 パスワードが間違っています")
        return False
    else:
        # Password correct.
        return True

def display_video_info(video, show_sponsors=True):
    st.markdown(f"[{video['title']}]({video['url']})")
    st.write(f"**アップロード日時**: {video['publishedAt']}")
    if show_sponsors:
        st.write(f"**視聴回数**: {video['viewCount']}")
        st.image(video['thumbnailUrl'])
        if video['sponsors']:
            st.write(f"**スポンサー**: {', '.join(video['sponsors'])}")
        with st.expander("詳細を表示"):
            st.write(video['description'])

if check_password():
    st.markdown("<h1 style='font-size: 24px;'>YouTube スポンサー動画検索アプリ</h1>", unsafe_allow_html=True)
    st.write('YouTubeの動画を検索し、スポンサー情報が含まれている動画を表示します。')

    search_type = st.radio("検索タイプを選択", ["キーワード検索", "カテゴリー検索", "トレンド"])

    if search_type == "キーワード検索":
        query = st.text_input('検索ワードを入力してください', '韓国')
        category = "すべて"
    elif search_type == "カテゴリー検索":
        category = st.selectbox("カテゴリーを選択", YOUTUBE_CATEGORIES)
        query = category
    else:  # トレンド
        query = ""
        category = "すべて"

    total_results = st.slider('検索件数', min_value=50, max_value=1000, value=200, step=50)
    order = 'date' if search_type != "キーワード検索" else 'relevance'

    # 検索ボタンとキャッシュクリアボタンを横に並べる
    col1, col2 = st.columns(2)
    with col1:
        search_button = st.button('検索')
    with col2:
        cache_clear_button = st.button('キャッシュをクリア')

    if cache_clear_button:
        clear_cache()

    if search_button:
        youtube = build('youtube', 'v3', developerKey=API_KEY)
        category_id = get_category_id(youtube, category) if category != "すべて" else ""

        st.write(f'{"トレンド" if search_type == "トレンド" else query} で動画を検索しています...')
        videos = search_videos_with_paging(API_KEY, query, total_results=total_results, order=order, video_category=category_id)
        
        # 以下、既存の検索結果表示ロジック
        if videos:
            # 新着順に並べ替え
            videos = sorted(videos, key=lambda x: x['publishedAt'], reverse=True)
            
            st.write(f'合計 {len(videos)} 件の動画が見つかりました。')
            
            # スポンサー情報がある動画とない動画を分ける
            sponsored_videos = [v for v in videos if v['sponsors']]
            non_sponsored_videos = [v for v in videos if not v['sponsors']]
            
            st.write(f'スポンサー情報が含まれている動画: {len(sponsored_videos)} 件')
            st.write(f'スポンサー情報が含まれていない動画: {len(non_sponsored_videos)} 件')
            
            # スポンサー情報がある動画を表示
            if sponsored_videos:
                st.subheader("スポンサー情報が含まれている動画")
                for video in sponsored_videos:
                    display_video_info(video, show_sponsors=True)
            
            # スポンサー情報がない動画を表示（簡略化した情報）
            if non_sponsored_videos:
                st.subheader("スポンサー情報が含まれていない動画")
                for video in non_sponsored_videos:
                    display_video_info(video, show_sponsors=False)
        else:
            st.write('動画が見つかりませんでした。')

    st.sidebar.write(f"APIリクエスト数: {st.session_state.api_requests} / 10000")
    st.write("実行コマンド: `streamlit run app3.py`")