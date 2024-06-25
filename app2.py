import streamlit as st
from googleapiclient.discovery import build
import re
from googleapiclient.errors import HttpError
import pickle
import os
from datetime import datetime, timedelta
import hmac
import hashlib
import toml

# YouTube Data APIのAPIキー
API_KEY = 'AIzaSyDM2F_A0kreCYAONjzGq4RBvKTvOU3aII4'

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

# 除外するパターン
exclude_patterns = [
    r'動画提供',
    r'楽曲提供',
    r'音楽提供',
    r'BGM提供',
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
    return sponsors

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
                
                if sponsors_found:
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

def search_videos_with_paging(api_key, query, max_results_per_page=50, total_results=200):
    cache_file = f"cache_{query.replace(' ', '_')}.pkl"
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
            search_response = youtube.search().list(
                q=query,
                part='snippet',
                type='video',
                maxResults=max_results_per_page,
                order='relevance',
                pageToken=next_page_token
            ).execute()
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

if check_password():
    # Streamlitのインターフェース設定
    st.title('YouTube スポンサー動画検索アプリ')
    st.write('指定されたキーワードでYouTube動画を検索し、スポンサー情報が含まれている動画を表示します。')

    # 検索クエリの入力
    query = st.text_input('検索ワードを入力してください', '台湾旅行')

    # 検索件数の設定
    total_results = st.slider('検索件数', min_value=50, max_value=1000, value=200, step=50)

    # 検索ボタン
    if st.button('検索'):
        st.write(f'検索ワード: {query} でスポンサー付き動画を検索しています...')
        videos = search_videos_with_paging(API_KEY, query, total_results=total_results)
        
        if videos:
            st.write(f'スポンサー情報が含まれている動画が {len(videos)} 件見つかりました！')
            for video in videos:
                st.markdown(f"### {video['title']}")
                st.write(f"**視聴回数**: {video['viewCount']}")
                st.write(f"**アップロード日時**: {video['publishedAt']}")
                st.image(video['thumbnailUrl'])
                st.write(f"**URL**: [こちらをクリック]({video['url']})")
                
                st.write(f"**スポンサー**: {', '.join(video['sponsors'])}")
                
                with st.expander("詳細を表示"):
                    st.write(video['description'])
        else:
            st.write('スポンサー情報が含まれている動画が見つかりませんでした。')

    # APIリクエスト数の表示
    st.sidebar.write(f"APIリクエスト数: {st.session_state.api_requests} / 10000")

    # 実行コマンドを表示
    st.write("実行コマンド: `streamlit run app2.py`")
