import yaml
import os
from dotenv import load_dotenv

def load_config(file_path: str = "config/config.yaml") -> dict:
    load_dotenv()
    with open(file_path, "r") as f:
        config = yaml.safe_load(f)
    config["api"]["bingx"]["api_key"] = os.getenv("BINGX_API_KEY")
    config["api"]["bingx"]["secret"] = os.getenv("BINGX_SECRET")
    config["telegram"]["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN")
    config["telegram"]["chat_id"] = os.getenv("TELEGRAM_CHAT_ID")
    return config
