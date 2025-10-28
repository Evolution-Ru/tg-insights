import os
import asyncio
from dotenv import load_dotenv

from telethon import TelegramClient, utils
from telethon.sessions import StringSession

# from data/accounts/ychukaev/.env
load_dotenv('data/accounts/ychukaev/.env') 

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")
session_string = os.getenv("TELEGRAM_SESSION_STRING")
session_name = os.getenv("TELEGRAM_SESSION_NAME", "anon")

# run convert.bash
os.system("cd /Users/ychukaev/Desktop/work/innerdev/salesevolution/telegram-storage/video2circle && ./convert.bash")

# Telethon client
if session_string:
    client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
else:
    client = TelegramClient(session_name, int(api_id), api_hash)

async def main():
    async with client:
        output_dir = "/Users/ychukaev/Desktop/work/innerdev/salesevolution/telegram-storage/video2circle/output"
        
        # Check if output directory exists
        if not os.path.exists(output_dir):
            print("Output directory doesn't exist. Conversion may have failed.")
            return
            
        # order by name
        for file in sorted(os.listdir(output_dir)): 
            if file.endswith(".mp4"):
                file_path = f"{output_dir}/{file}"
                print(f"Sending {file}...")
                await client.send_file(
                    "me", file_path, 
                    video_note=True,
                )
                print(f"Sent {file}, waiting 60 seconds...")
                await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
