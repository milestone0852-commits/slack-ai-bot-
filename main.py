import os
import google.generativeai as genai
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from google.colab import userdata
import time
import json
import re
import traceback
import tweepy

# --- ### 修正箇所 ### 安全なキー読み込みのための関数 ---
def get_secret(key):
    """ColabとRenderの両方の環境でシークレットを読み込むための関数"""
    try:
        # Google Colab環境の場合
        from google.colab import userdata
        return userdata.get(key)
    except (ImportError, ModuleNotFoundError):
        # Render.comなどのサーバー環境の場合
        return os.environ.get(key)

# --- APIキーとトークンの設定 ---
try:
    # ### 修正箇所 ### コードから直接の記述を削除し、安全な方法で読み込む
    SLACK_BOT_TOKEN = get_secret('SLACK_BOT_TOKEN')
    SLACK_APP_TOKEN = get_secret('SLACK_APP_TOKEN')
    GEMINI_API_KEY = get_secret('GEMINI_API_KEY')
    TWITTER_API_KEY = get_secret('TWITTER_API_KEY')
    TWITTER_API_SECRET = get_secret('TWITTER_API_SECRET')
    TWITTER_ACCESS_TOKEN = get_secret('TWITTER_ACCESS_TOKEN')
    TWITTER_ACCESS_TOKEN_SECRET = get_secret('TWITTER_ACCESS_TOKEN_SECRET')
    
    genai.configure(api_key=GEMINI_API_KEY)
    
    if not all([SLACK_BOT_TOKEN, SLACK_APP_TOKEN, GEMINI_API_KEY, TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
        raise ValueError("必要なAPIキーまたはトークンが1つ以上設定されていません。")

except Exception as e:
    print(f"致命的なエラー: APIキーの読み込みに失敗しました。環境変数またはColabシークレットを確認してください。")
    print(f"エラー詳細: {e}")
    exit()

# --- プロンプト定義 (変更なし) ---
COMMON_RULES = """
# あなたの役割
あなたは、世界トップクラスの仮想通貨分野専門SNSコンサルタントです。あなたの仕事は、Twitterの投稿として完璧な「部品」をJSON形式で生成することです。
# JSON出力のルール
- `title`キーには、絵文字を含んだキャッチーな見出しを入れてください。
- `title`キーには、曜日情報は絶対に入れないでください。
- `hashtags`キーの値は、関連性の高いハッシュタグをリスト（配列）形式で3つまで入れてください。
- `full_content`キーの値は、投稿の本文です。
# 厳守すべきルール
- **文字数制限:** `title`, `full_content`, `hashtags`を全て合計した文字数が、**必ず135文字以内**になるようにしてください。これは絶対のルールです。
- **長文の扱い:** もし内容が長くなる場合は、スレッド投稿を前提とし、**最初の1投稿分として130文字程度**で区切りの良い文章を作成してください。
- **品質:** 具体的で、専門用語を適切に使い、示唆に富んだ内容にすること。
"""
PROMPT_WEEKLY_PLAN = """{common_rules}
# 指示
（省略）
**JSON形式:** `{{ "plan": [{{ "day": "月曜日", "time_slot": "朝", "post_type": "投稿の型", "title": "見出し", "full_content": "投稿本文(130字以内)", "hashtags": ["#"] }}, ...] }}`
ユーザーからのリクエスト： "{user_instruction}"
"""
PROMPT_SINGLE_POST = """{common_rules}
# 指示
（省略）
**JSON形式:** `{{ "post": {{ "post_type": "投稿の型", "title": "見出し", "full_content": "投稿本文(130字以内)", "hashtags": ["#"] }} }}`
ユーザーからのリクエスト： "{user_instruction}"
"""
# --- プロンプト定義ここまで ---

# --- 品質保証関数 (変更なし) ---
def assemble_and_validate_post(post_data):
    title = post_data.get("title", "")
    full_content = post_data.get("full_content", "コンテンツが生成されませんでした。")
    hashtags = post_data.get("hashtags", [])
    valid_hashtags = hashtags[:3]
    hashtag_string = " ".join(valid_hashtags)
    if len(title) + len(full_content) + len(hashtag_string) < 140:
        return f"{title}\n{full_content}\n\n{hashtag_string}"
    else:
        tweet_parts = []
        text_to_split = f"{title}\n{full_content}"
        MAX_CONTENT_LENGTH = 130
        while len(text_to_split) > 0:
            if len(text_to_split) <= MAX_CONTENT_LENGTH:
                tweet_parts.append(text_to_split)
                break
            chunk = text_to_split[:MAX_CONTENT_LENGTH + 1]
            split_pos = -1
            for delimiter in ['。', '、', '\n']:
                pos = chunk.rfind(delimiter)
                if pos != -1:
                    split_pos = pos
                    break
            if split_pos == -1: split_pos = MAX_CONTENT_LENGTH
            part_to_add = text_to_split[:split_pos + 1].strip()
            if part_to_add: tweet_parts.append(part_to_add)
            text_to_split = text_to_split[split_pos + 1:].strip()
        final_tweets = []
        total_parts = len(tweet_parts)
        for i, part in enumerate(tweet_parts):
            header = f"({i+1}/{total_parts})\n"
            footer = f"\n\n{hashtag_string}" if (i == total_parts - 1) else ""
            final_tweets.append(f"{header}{part}{footer}")
        return final_tweets

# --- Twitter投稿関数 (変更なし) ---
def post_to_twitter(post_content):
    try:
        client = tweepy.Client(
            consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_TOKEN_SECRET
        )
        if isinstance(post_content, list):
            previous_tweet_id = None
            for i, text in enumerate(post_content):
                response = client.create_tweet(text=text, in_reply_to_tweet_id=previous_tweet_id)
                new_tweet_id = response.data['id']
                print(f"スレッド投稿 {i+1}/{len(post_content)} が成功。 Tweet ID: {new_tweet_id}")
                previous_tweet_id = new_tweet_id
                time.sleep(2)
            return f"スレッド投稿（全{len(post_content)}件）が成功しました！"
        else:
            response = client.create_tweet(text=post_content)
            print(f"単一投稿が成功。 Tweet ID: {response.data['id']}")
            return "単一投稿が成功しました！"
    except Exception as e:
        print(f"Twitterへの投稿中にエラーが発生しました: {e}")
        return f"Twitterへの投稿に失敗しました: {e}"

# --- Slackアプリ (変更なし) ---
app = App(token=SLACK_BOT_TOKEN)
DRAFT_POSTS = {}

@app.event("app_mention")
def handle_mention(event, say, client):
    print("Running v51: Secure Production Version")
    thread_ts = event.get("ts")
    user_id = event.get("user")
    try:
        user_instruction = event["text"].split(">", 1)[-1].strip()
        prompt_template = PROMPT_WEEKLY_PLAN if "週" in user_instruction else PROMPT_SINGLE_POST
        common_format_args = {"common_rules": COMMON_RULES, "user_instruction": user_instruction}
        final_prompt = prompt_template.format(**common_format_args)
        thinking_message_ts = say(text="承知しました。AIに設計図を依頼し、投稿を組み立てます...", thread_ts=thread_ts).get("ts")
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(final_prompt)
        raw_text, json_text = response.text, None
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
        if json_match: json_text = json_match.group(1)
        else:
            start_index, end_index = raw_text.find('{'), raw_text.rfind('}')
            if start_index != -1 and end_index != -1: json_text = raw_text[start_index:end_index+1]
        if not json_text: raise ValueError("AIが有効なJSONを生成しませんでした。")
        json_data = json.loads(json_text)
        def post_draft(post_obj, context_header, original_thread_ts):
            assembled_post = assemble_and_validate_post(post_obj)
            preview_text = assembled_post[0] if isinstance(assembled_post, list) else assembled_post
            draft_message = f"--- **{context_header}** ---\n{preview_text}"
            draft_id = f"draft_{int(time.time() * 1000)}"
            DRAFT_POSTS[draft_id] = { "text": assembled_post, "day": post_obj.get("day"), "time_slot": post_obj.get("time_slot"), "thread_ts": original_thread_ts }
            client.chat_postEphemeral(
                channel=event["channel"], user=user_id, thread_ts=original_thread_ts, text=draft_message,
                blocks=[
                    {"type": "section", "text": {"type": "mrkdwn", "text": draft_message}},
                    {"type": "actions", "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "承認 ＆ Twitter投稿", "emoji": True}, "style": "primary", "action_id": "approve_and_post", "value": draft_id},
                        {"type": "button", "text": {"type": "plain_text", "text": "修正を指示する", "emoji": True}, "action_id": "redo_post", "value": str(original_thread_ts)}
                    ]}
                ]
            )
        if "plan" in json_data:
            for day_plan in json_data.get("plan", []):
                day, time_slot, post_type = day_plan.get("day", "曜日不明"), day_plan.get("time_slot", ""), day_plan.get("post_type", "タイプ不明")
                post_draft(day_plan, f"{day} {time_slot} ({post_type}) の下書き", thread_ts)
                time.sleep(1)
        elif "post" in json_data:
            post_draft(json_data.get("post", {}), "単独投稿の下書き", thread_ts)
        client.chat_delete(channel=event["channel"], ts=thinking_message_ts)
    except Exception as e:
        tb_str = traceback.format_exc()
        print(f"---!!! 根本的なエラーが発生しました !!!---\n{tb_str}")
        error_message = f"申し訳ありません、エラーが発生しました。\n`{type(e).__name__}: {e}`"
        say(text=error_message, thread_ts=thread_ts)

@app.action("approve_and_post")
def handle_approve_and_post_action(ack, body, respond, logger, say):
    ack()
    try:
        draft_id = body["actions"][0]["value"]
        approved_data = DRAFT_POSTS.pop(draft_id, None)
        if approved_data is None:
            respond(text="エラー：この下書きは見つかりませんでした。", replace_original=True)
            return
        post_content = approved_data.get("text")
        day = approved_data.get("day", "未指定")
        time_slot = approved_data.get("time_slot", "未指定")
        thread_ts = approved_data.get("thread_ts")
        respond(text=f"✅ **{day} {time_slot}** の投稿を承認しました。Twitterに投稿します...", replace_original=True)
        result_message = post_to_twitter(post_content)
        if thread_ts:
            say(text=f"🕊️ **{day} {time_slot}** の投稿処理が完了しました。\n結果: {result_message}", thread_ts=thread_ts)
    except Exception as e:
        logger.error(f"承認＆投稿処理中にエラー: {e}")
        respond(text=f"エラーが発生しました: {e}", replace_original=True)

@app.action("redo_post")
def handle_redo_action(ack, body, say, respond):
    ack()
    thread_ts = body["actions"][0]["value"]
    respond(text="🔄 修正を指示しました。スレッドでボットが質問します。", replace_original=True)
    say(text="かしこまりました。この投稿案について、どのように修正しますか？", thread_ts=thread_ts)

# --- アプリの起動 ---
if __name__ == "__main__":
    try:
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        print("⚡️ BoltアプリがSocket Modeで起動しました！ (v51 セキュリティ修正版)")
        handler.start()
    except Exception as e:
        print(f"---!!! アプリの起動に失敗しました !!!---")
        print(f"エラー: {e}")
