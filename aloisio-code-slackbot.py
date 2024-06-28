import os
import requests
import logging
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime
from replit import db

slack_client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
app = App(token=os.environ["SLACK_BOT_TOKEN"])
last_processed_message_ts = {}

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


def generate_response(thread_id, user_message, user_name):
  url = f"https://g4ai.onrender.com/api/v1/prediction/{os.environ['FLOWISE_CANVA_ID_Isaque']}"
  headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {os.environ['AUTHORIZATION_TOKEN']}"
  }
  data = {
      "question": f"{user_name}: {user_message}",
      "overrideConfig": {
          "sessionId": thread_id
      }
  }
  try:
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    assistant_message = response.json()["text"]
    return assistant_message
  except requests.RequestException as e:
    logger.error(f"Failed to generate response from the API: {e}")
    return "Sorry, I encountered an error trying to process your request."


def fetch_thread_history(channel_id, thread_ts, last_known_ts):
  messages = []
  try:
    response = slack_client.conversations_replies(channel=channel_id,
                                                  ts=thread_ts)
    while True:
      batch_messages = response['messages']
      messages.extend([
          msg for msg in batch_messages
          if float(msg['ts']) > float(last_known_ts)
      ])
      if response["has_more"]:
        response = slack_client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            cursor=response["response_metadata"]["next_cursor"])
      else:
        break
  except SlackApiError as e:
    logger.error(f"Error fetching thread history: {e}")
  return messages


@app.event("app_mention")
def handle_mention(body, say):
  event = body["event"]
  channel_id = event["channel"]
  thread_ts = event.get("thread_ts", event["ts"])
  user_id = event["user"]
  user_message = event["text"].split(" ", maxsplit=1)[1].strip() if len(
      event["text"].split(" ", maxsplit=1)) > 1 else ""

  last_ts = last_processed_message_ts.get(thread_ts, "0")
  new_messages = fetch_thread_history(channel_id, thread_ts, last_ts)
  last_processed_message_ts[thread_ts] = event[
      'ts']  # Update with the current event timestamp

  user_name = get_user_name(user_id)

  # Assume new_messages includes messages to be processed for context
  context = " ".join(
      msg['text']
      for msg in new_messages)  # Simplified example of how to build context
  full_message = f"{context} {user_name}: {user_message}"
  response_text = generate_response(thread_ts, full_message, user_name)
  store_interaction(thread_ts, user_id, user_name, user_message, response_text)
  say(response_text, thread_ts=thread_ts)


def get_user_name(user_id):
  try:
    user_info = slack_client.users_info(user=user_id)
    return user_info["user"]["real_name"]
  except SlackApiError as e:
    logger.error(f"Error fetching user info: {e}")
    return None


def store_interaction(thread_id, user_id, user_name, user_message,
                      bot_response):
  timestamp = datetime.now().isoformat()
  key = f"{thread_id}-{timestamp}"
  db[key] = {
      "thread_id": thread_id,
      "user_id": user_id,
      "user_name": user_name,
      "user_message": user_message,
      "bot_response": bot_response,
      "timestamp": timestamp
  }


@app.event("message")
def handle_message_events(body, logger):
  logger.info("Received message: %s", body)


if __name__ == "__main__":
  handler = SocketModeHandler(app, os.environ["SLACK_SIGNING_SECRET"])
  handler.start()
