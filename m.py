import os
import asyncio
import zipfile
import shutil
import re
import time
import sys
import subprocess
import io
import aiohttp
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image
import nest_asyncio
from telegram import Bot, InputFile, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
import logging
import yaml

# Apply nest_asyncio
nest_asyncio.apply()

# ==================== LOAD CONFIG ====================
def load_config():
    config_path = Path("config.yml")
    if not config_path.exists():
        print("❌ config.yml not found. Please create it from the example.")
        sys.exit(1)
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

config = load_config()

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = config['bot_token']
TARGET_CHANNEL_ID = config['target_channel']
ZIP_PASSWORD = config['archive_password']
ALLOWED_USERS = config.get('allowed_users', [])
DOWNLOAD_DIR = Path(config.get('download_dir', 'downloads'))
EXTRACT_DIR = Path(config.get('extract_dir', 'extracted'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Color codes for terminal
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_banner():
    banner = f"""
{Colors.CYAN}{'='*60}
{Colors.BOLD}    TELEGRAM BOT FILE PROCESSOR v7.0
    Handles large files up to 2GB via direct download
    Supports: ZIP | RAR | 7Z | Images | Videos
{Colors.END}{Colors.CYAN}{'='*60}{Colors.END}
    """
    print(banner)

def ensure_directories():
    for dir_path in [DOWNLOAD_DIR, EXTRACT_DIR]:
        dir_path.mkdir(exist_ok=True)

def cleanup_directories():
    for dir_path in [DOWNLOAD_DIR, EXTRACT_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)

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

def extract_rar_with_unar(file_path: Path, extract_to: Path, password: str = None) -> bool:
    try:
        cmd = ['unar', '-o', str(extract_to), str(file_path)]
        if password:
            cmd.extend(['-p', password])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # Increased timeout
        return result.returncode == 0
    except Exception as e:
        logger.error(f"RAR extraction error: {e}")
        return False

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
            success = extract_rar_with_unar(file_path, extract_to, password)
            if success:
                return True, list(extract_to.rglob("*"))
            else:
                return False, []
        
        return False, []
    except Exception as e:
        logger.error(f"Extraction error: {e}")
        return False, []

def is_image_file(filepath: Path) -> bool:
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
    if filepath.suffix.lower() in image_extensions:
        return True
    try:
        with Image.open(filepath) as img:
            return True
    except:
        return False

def is_video_file(filepath: Path) -> bool:
    video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp'}
    return filepath.suffix.lower() in video_extensions

async def download_large_file(bot: Bot, file_id: str, file_path: Path, file_size: int) -> bool:
    """
    Download large files using direct URL (bypasses 20MB bot limit)
    """
    try:
        # Get file info to get the direct download URL
        file = await bot.get_file(file_id)
        
        # For large files, Telegram provides a direct download URL
        if file.file_path:
            download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file.file_path}"
        else:
            # Fallback to using file_id (will fail for files > 20MB)
            await file.download_to_drive(file_path)
            return True
        
        # Download using aiohttp with progress
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as response:
                if response.status == 200:
                    total_size = int(response.headers.get('content-length', file_size))
                    
                    # Show progress bar
                    downloaded = 0
                    with open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if downloaded % (1024 * 1024) == 0:  # Show every MB
                                progress = (downloaded / total_size) * 100
                                logger.info(f"Download progress: {progress:.1f}%")
                    
                    return True
                else:
                    logger.error(f"Failed to download: HTTP {response.status}")
                    return False
                    
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False

async def process_and_send(bot: Bot, file_path: Path, password: str, target_channel: str) -> Dict:
    """Process a file (archive or single) and send all media to channel."""
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
        
        # Find all media files
        media_files = []
        for f in extracted_files:
            if f.is_file() and (is_image_file(f) or is_video_file(f)):
                media_files.append(f)
        
        if not media_files:
            result['error'] = "No images or videos found in file"
            shutil.rmtree(temp_extract, ignore_errors=True)
            return result
        
        result['total_media'] = len(media_files)
        
        # Process and send each media file
        for idx, media_path in enumerate(media_files, 1):
            try:
                media_type = "📸 Image" if is_image_file(media_path) else "🎥 Video"
                file_size_mb = media_path.stat().st_size / (1024 * 1024)
                
                # Check if file is too large (>50MB)
                if file_size_mb > 50:
                    logger.warning(f"File too large ({file_size_mb:.1f}MB), splitting not supported yet")
                
                with open(media_path, 'rb') as f:
                    caption = f"{media_type} {idx}/{len(media_files)}\n📁 From: {file_path.name}"
                    await bot.send_document(
                        chat_id=target_channel,
                        document=InputFile(f, filename=media_path.name),
                        caption=caption
                    )
                result['sent_media'] += 1
                await asyncio.sleep(1)  # Avoid rate limits
                
            except Exception as e:
                result['failed_media'] += 1
                logger.error(f"Error sending {media_path.name}: {e}")
        
        # Cleanup
        shutil.rmtree(temp_extract, ignore_errors=True)
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Process error: {e}")
    
    return result

# ---------- Task Queue ----------
class TaskQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.processing = False

    async def add_task(self, task):
        await self.queue.put(task)
        if not self.processing:
            await self.process_queue()

    async def process_queue(self):
        self.processing = True
        try:
            while not self.queue.empty():
                task = await self.queue.get()
                await task()
                self.queue.task_done()
        finally:
            self.processing = False

task_queue = TaskQueue()

# ---------- Handlers ----------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    document = update.message.document
    file_name = document.file_name
    file_size = document.file_size
    size_mb = file_size / (1024 * 1024)

    status_msg = await update.message.reply_text(
        f"📥 **Added to queue:**\n"
        f"📁 {file_name}\n"
        f"💾 {size_mb:.1f} MB\n"
        f"⏳ Position: {task_queue.queue.qsize() + 1}",
        parse_mode='Markdown'
    )

    async def process():
        try:
            # Update status
            await status_msg.edit_text(
                f"🔄 **Downloading:** {file_name}\n"
                f"💾 {size_mb:.1f} MB"
            )
            
            # Download file (handles large files via direct URL)
            file_path = DOWNLOAD_DIR / file_name
            
            # Check if file is large (>20MB)
            if file_size > 20 * 1024 * 1024:  # 20MB limit for bot API
                await status_msg.edit_text(
                    f"📥 **Large file detected:** {file_name}\n"
                    f"Using direct download method..."
                )
                success = await download_large_file(context.bot, document.file_id, file_path, file_size)
            else:
                file = await context.bot.get_file(document.file_id)
                await file.download_to_drive(file_path)
                success = True
            
            if not success:
                await status_msg.edit_text(f"❌ **Download failed:** {file_name}")
                return
            
            await status_msg.edit_text(
                f"🔄 **Processing:** {file_name}\n"
                f"📦 Extracting media..."
            )

            # Process the file
            result = await process_and_send(
                context.bot,
                file_path,
                ZIP_PASSWORD,
                TARGET_CHANNEL_ID
            )

            # Send result
            if result['error']:
                await status_msg.edit_text(
                    f"❌ **Failed:** {file_name}\n"
                    f"Error: {result['error']}"
                )
            else:
                await status_msg.edit_text(
                    f"✅ **Completed:** {file_name}\n"
                    f"🎬 Media found: {result['total_media']}\n"
                    f"✅ Sent: {result['sent_media']}\n"
                    f"❌ Failed: {result['failed_media']}"
                )

            # Cleanup
            file_path.unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Error processing {file_name}: {e}")
            await status_msg.edit_text(
                f"❌ **Error:** {file_name}\n"
                f"{str(e)}"
            )

    await task_queue.add_task(process)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ Not authorized.")
        return

    video = update.message.video
    file_name = video.file_name or f"video_{update.message.message_id}.mp4"
    file_size = video.file_size
    size_mb = file_size / (1024 * 1024)

    status_msg = await update.message.reply_text(
        f"🎬 **Added to queue:**\n"
        f"📁 {file_name}\n"
        f"💾 {size_mb:.1f} MB\n"
        f"Position: {task_queue.queue.qsize() + 1}",
        parse_mode='Markdown'
    )

    async def process():
        try:
            await status_msg.edit_text(f"🔄 **Forwarding video:** {file_name}")
            await context.bot.send_video(
                chat_id=TARGET_CHANNEL_ID,
                video=video.file_id,
                caption=f"🎥 {file_name}"
            )
            await status_msg.edit_text(f"✅ **Forwarded:** {file_name}")
        except Exception as e:
            logger.error(f"Error sending video: {e}")
            await status_msg.edit_text(f"❌ **Failed:** {e}")

    await task_queue.add_task(process)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ Not authorized.")
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    status_msg = await update.message.reply_text(
        f"📸 **Added to queue**\nPosition: {task_queue.queue.qsize() + 1}",
        parse_mode='Markdown'
    )

    async def process():
        try:
            await status_msg.edit_text("📸 **Processing photo...**")
            
            # Download photo
            file_path = DOWNLOAD_DIR / f"photo_{int(time.time())}.jpg"
            await file.download_to_drive(file_path)

            # Send as document
            with open(file_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=TARGET_CHANNEL_ID,
                    document=InputFile(f, filename=file_path.name),
                    caption=f"📸 Photo from @{update.effective_user.username or update.effective_user.first_name}"
                )
            await status_msg.edit_text("✅ **Photo sent!**")

            # Cleanup
            file_path.unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await status_msg.edit_text(f"❌ **Failed:** {e}")

    await task_queue.add_task(process)

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "🤖 **Bot File Processor v7.0**\n\n"
        "Send me any file and I'll:\n"
        "1️⃣ Download it (handles up to 2GB)\n"
        "2️⃣ Extract media (ZIP/RAR/7Z)\n"
        "3️⃣ Send all images/videos to channel\n\n"
        "**Multiple files?** They're queued and processed one by one.\n\n"
        f"🎯 **Target channel:** {TARGET_CHANNEL_ID}\n"
        f"🔐 **Archive password:** `{ZIP_PASSWORD}`\n\n"
        "Send me files to get started!"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_msg = (
        "📖 **Help**\n\n"
        "**Commands:**\n"
        "/start - Show info\n"
        "/help - This help\n"
        "/status - Queue status\n\n"
        "**Large Files:**\n"
        "• Files >20MB use direct download\n"
        "• Supports files up to 2GB\n"
        "• Shows download progress\n\n"
        "**Supported:**\n"
        "ZIP, RAR, 7Z (password: cosplaytele)\n"
        "Images, Videos\n\n"
        "**Media:**\n"
        "• Sent as documents (original quality)\n"
        "• No compression or upscaling"
    )
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    queue_size = task_queue.queue.qsize()
    status_text = f"📊 **Queue status:**\n"
    if queue_size == 0:
        status_text += "No tasks waiting."
    else:
        status_text += f"{queue_size} task(s) waiting."
    await update.message.reply_text(status_text, parse_mode='Markdown')

def main():
    print_banner()
    
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print(f"{Colors.FAIL}✗ Please add your bot token in config.yml!{Colors.END}")
        return

    ensure_directories()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print(f"{Colors.GREEN}✓ Bot started!{Colors.END}")
    print(f"{Colors.CYAN}✓ Large file support enabled (up to 2GB){Colors.END}")
    print(f"{Colors.CYAN}✓ Queue system active{Colors.END}")
    print(f"{Colors.GREEN}{'='*50}{Colors.END}")

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Bot stopped by user{Colors.END}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.FAIL}Fatal error: {e}{Colors.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
