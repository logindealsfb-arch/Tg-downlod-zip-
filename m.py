import os
import asyncio
import zipfile
import shutil
import re
import time
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image
import nest_asyncio
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaDocument, Document, MessageMediaPhoto
from telethon.errors import FloodWaitError
import logging

# Apply nest_asyncio
nest_asyncio.apply()

# ==================== CONFIGURATION ====================
# Get from https://my.telegram.org
API_ID = 24444776  # ← REPLACE WITH YOUR API ID
API_HASH = "f04986e0cbd332b2b2e6350f314f49b0"  # ← REPLACE WITH YOUR API HASH
PHONE_NUMBER = "+919904064485"  # ← REPLACE WITH YOUR PHONE NUMBER

# Bot token for sending to channel
BOT_TOKEN = "8017395524:AAH8gY_CKKZU7hGJJOlX7WztOmQ7Q-J1V5U"
TARGET_CHANNEL_ID = -1003107433425  # Numeric ID of target channel
ZIP_PASSWORD = "cosplaytele"
ALLOWED_USERS = []  # Leave empty for all users

# Directories
DOWNLOAD_DIR = Path("downloads")
EXTRACT_DIR = Path("extracted")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Colors for terminal
class Colors:
    GREEN = '\033[92m'
    CYAN = '\033[96m'
    FAIL = '\033[91m'
    END = '\033[0m'

def print_banner():
    banner = f"""
{Colors.CYAN}{'='*60}
{Colors.GREEN}    TELEGRAM FILE PROCESSOR v10.0 (User Account)
    Downloads ANY file size using your Telegram account!
    Sends to channel using Bot
{Colors.CYAN}{'='*60}{Colors.END}
    """
    print(banner)

def ensure_directories():
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    EXTRACT_DIR.mkdir(exist_ok=True)

# ==================== LINK PARSING ====================
def parse_telegram_link(link: str) -> Optional[Tuple[str, int]]:
    """Parse Telegram message link"""
    pattern1 = r'https?://t\.me/([^/]+)/(\d+)'
    match = re.match(pattern1, link)
    if match:
        return (match.group(1), int(match.group(2)))
    
    pattern2 = r'https?://t\.me/c/(\d+)/(\d+)'
    match = re.match(pattern2, link)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    
    return None

# ==================== ARCHIVE EXTRACTION ====================
def detect_archive_type(file_path: Path) -> Optional[str]:
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(4)
            if magic[:2] == b'PK':
                return 'zip'
            elif magic[:4] == b'Rar!':
                return 'rar'
            elif magic[:2] == b'7z':
                return '7z'
        ext = file_path.suffix.lower()
        if ext == '.zip':
            return 'zip'
        elif ext == '.rar':
            return 'rar'
        elif ext == '.7z':
            return '7z'
        return None
    except:
        return None

def extract_archive(file_path: Path, extract_to: Path, password: str = None) -> Tuple[bool, List[Path]]:
    try:
        archive_type = detect_archive_type(file_path)
        
        if not archive_type:
            logger.info(f"Not an archive: {file_path.name}")
            shutil.copy2(file_path, extract_to / file_path.name)
            return True, [extract_to / file_path.name]
        
        logger.info(f"Extracting {archive_type.upper()}: {file_path.name}")
        
        if archive_type == 'zip':
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                for file_name in zip_ref.namelist():
                    try:
                        if password:
                            zip_ref.extract(file_name, extract_to, pwd=password.encode())
                        else:
                            zip_ref.extract(file_name, extract_to)
                    except RuntimeError:
                        if password:
                            zip_ref.extract(file_name, extract_to)
                return True, list(extract_to.rglob("*"))
        
        elif archive_type in ['rar', '7z']:
            cmd = ['unar', '-o', str(extract_to), str(file_path)]
            if password:
                cmd.extend(['-p', password])
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            if result.returncode == 0:
                return True, list(extract_to.rglob("*"))
            return False, []
        
        return False, []
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        return False, []

def is_media_file(filepath: Path) -> bool:
    media_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
        '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp'
    }
    return filepath.suffix.lower() in media_extensions

# ==================== SEND TO CHANNEL USING BOT ====================
from telegram import Bot, InputFile

async def send_to_channel(file_path: Path, caption: str, index: int, total: int):
    """Send file to channel using bot"""
    try:
        bot = Bot(token=BOT_TOKEN)
        with open(file_path, 'rb') as f:
            await bot.send_document(
                chat_id=TARGET_CHANNEL_ID,
                document=InputFile(f, filename=file_path.name),
                caption=f"{caption} {index}/{total}"
            )
        return True
    except Exception as e:
        logger.error(f"Send error: {e}")
        return False

# ==================== PROCESS AND SEND ====================
async def process_and_send(file_path: Path, password: str, file_name: str) -> Dict:
    """Process a file and send all media to channel"""
    result = {
        'total_media': 0,
        'sent_media': 0,
        'failed_media': 0,
        'error': None
    }
    
    try:
        timestamp = int(time.time())
        temp_extract = EXTRACT_DIR / f"extract_{timestamp}"
        temp_extract.mkdir(exist_ok=True)
        
        # Extract archive
        success, extracted_files = extract_archive(file_path, temp_extract, password)
        if not success:
            result['error'] = "Failed to extract archive"
            shutil.rmtree(temp_extract, ignore_errors=True)
            return result
        
        # Find media files
        media_files = [f for f in extracted_files if f.is_file() and is_media_file(f)]
        
        if not media_files:
            result['error'] = "No images or videos found"
            shutil.rmtree(temp_extract, ignore_errors=True)
            return result
        
        result['total_media'] = len(media_files)
        
        # Send each media file
        for idx, media_path in enumerate(media_files, 1):
            try:
                media_type = "📸 Image" if media_path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'} else "🎥 Video"
                success = await send_to_channel(media_path, media_type, idx, len(media_files))
                if success:
                    result['sent_media'] += 1
                else:
                    result['failed_media'] += 1
                await asyncio.sleep(1)
            except Exception as e:
                result['failed_media'] += 1
                logger.error(f"Error sending {media_path.name}: {e}")
        
        shutil.rmtree(temp_extract, ignore_errors=True)
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Process error: {e}")
    
    return result

# ==================== MAIN BOT LOGIC ====================
class FileProcessor:
    def __init__(self):
        self.client = None
        self.task_queue = asyncio.Queue()
        self.processing = False
    
    async def start(self):
        """Start the client and message handler"""
        self.client = TelegramClient('session', API_ID, API_HASH)
        await self.client.start(phone=PHONE_NUMBER)
        logger.info(f"✅ Logged in as: {await self.client.get_me()}")
        
        # Start processing queue
        asyncio.create_task(self.process_queue())
        
        # Handle incoming messages
        @self.client.on(events.NewMessage)
        async def handler(event):
            await self.handle_message(event)
        
        logger.info("✅ Bot is running! Send me a Telegram link or file...")
        await self.client.run_until_disconnected()
    
    async def handle_message(self, event):
        """Handle incoming messages"""
        user_id = event.sender_id
        
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            await event.reply("❌ Not authorized.")
            return
        
        # Check if it's a text message (link)
        if event.message.text:
            link = event.message.text.strip()
            
            # Check if it's a Telegram link
            if 't.me/' in link:
                await self.handle_link(event, link)
            else:
                await event.reply("❌ Please send a valid Telegram link (t.me/...) or upload a file.")
            return
        
        # Check if it's a file
        elif event.message.media:
            await self.handle_file(event)
            return
    
    async def handle_link(self, event, link: str):
        """Handle Telegram message links"""
        status_msg = await event.reply(f"🔗 **Processing link:**\n{link}\n\n⏳ Fetching file...")
        
        async def process():
            try:
                # Parse link
                parsed = parse_telegram_link(link)
                if not parsed:
                    await status_msg.edit("❌ Invalid link format")
                    return
                
                channel, msg_id = parsed
                
                # Get the message
                if isinstance(channel, int):
                    entity = channel
                else:
                    entity = channel
                
                message = await self.client.get_messages(entity, ids=msg_id)
                
                if not message or not message.media:
                    await status_msg.edit("❌ No file found in message")
                    return
                
                # Get file info
                file_name = None
                file_size = 0
                
                if isinstance(message.media, MessageMediaDocument):
                    document = message.media.document
                    for attr in document.attributes:
                        if hasattr(attr, 'file_name'):
                            file_name = attr.file_name
                            break
                    file_size = document.size
                
                if not file_name:
                    file_name = f"file_{msg_id}"
                
                await status_msg.edit(f"📥 **Downloading:** {file_name}\n💾 {file_size/(1024*1024):.1f} MB")
                
                # Download file
                file_path = DOWNLOAD_DIR / file_name
                await self.client.download_media(message, file=str(file_path))
                
                await status_msg.edit(f"✅ **Downloaded:** {file_name}\n🔄 Extracting media...")
                
                # Process and send
                result = await process_and_send(file_path, ZIP_PASSWORD, file_name)
                
                if result['error']:
                    await status_msg.edit(f"❌ **Failed:** {file_name}\nError: {result['error']}")
                else:
                    await status_msg.edit(f"✅ **Completed:** {file_name}\n🎬 Media sent: {result['sent_media']}/{result['total_media']}")
                
                # Cleanup
                file_path.unlink(missing_ok=True)
                
            except FloodWaitError as e:
                await status_msg.edit(f"⏳ Rate limited. Waiting {e.seconds} seconds...")
                await asyncio.sleep(e.seconds)
                await process()
            except Exception as e:
                logger.error(f"Error: {e}")
                await status_msg.edit(f"❌ **Error:** {str(e)}")
        
        await self.add_task(process)
    
    async def handle_file(self, event):
        """Handle direct file uploads"""
        # Download file info
        message = event.message
        file_name = None
        file_size = 0
        
        if isinstance(message.media, MessageMediaDocument):
            document = message.media.document
            for attr in document.attributes:
                if hasattr(attr, 'file_name'):
                    file_name = attr.file_name
                    break
            file_size = document.size
        
        if not file_name:
            file_name = f"file_{int(time.time())}"
        
        status_msg = await event.reply(
            f"📥 **Added to queue:**\n"
            f"📁 {file_name}\n"
            f"💾 {file_size/(1024*1024):.1f} MB\n"
            f"⏳ Position: {self.task_queue.qsize() + 1}"
        )
        
        async def process():
            try:
                await status_msg.edit(f"🔄 **Downloading:** {file_name}")
                
                # Download file
                file_path = DOWNLOAD_DIR / file_name
                await self.client.download_media(message, file=str(file_path))
                
                await status_msg.edit(f"✅ **Downloaded:** {file_name}\n🔄 Extracting media...")
                
                # Process and send
                result = await process_and_send(file_path, ZIP_PASSWORD, file_name)
                
                if result['error']:
                    await status_msg.edit(f"❌ **Failed:** {file_name}\nError: {result['error']}")
                else:
                    await status_msg.edit(f"✅ **Completed:** {file_name}\n🎬 Media sent: {result['sent_media']}/{result['total_media']}")
                
                # Cleanup
                file_path.unlink(missing_ok=True)
                
            except Exception as e:
                logger.error(f"Error: {e}")
                await status_msg.edit(f"❌ **Error:** {str(e)}")
        
        await self.add_task(process)
    
    async def add_task(self, task):
        await self.task_queue.put(task)
        if not self.processing:
            await self.process_queue()
    
    async def process_queue(self):
        self.processing = True
        try:
            while not self.task_queue.empty():
                task = await self.task_queue.get()
                await task()
                self.task_queue.task_done()
        finally:
            self.processing = False

# ==================== MAIN ====================
async def main():
    print_banner()
    
    # Check config
    if API_ID == 123456 or API_HASH == "your_api_hash_here":
        print(f"{Colors.FAIL}✗ Please edit the script and add your API_ID and API_HASH from https://my.telegram.org{Colors.END}")
        return
    
    if PHONE_NUMBER == "+1234567890":
        print(f"{Colors.FAIL}✗ Please add your phone number with country code{Colors.END}")
        return
    
    ensure_directories()
    
    processor = FileProcessor()
    await processor.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.GREEN}Bot stopped{Colors.END}")
        sys.exit(0)
