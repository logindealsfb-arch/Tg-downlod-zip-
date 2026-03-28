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
from telegram import Bot, InputFile, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging
import aiohttp

# Apply nest_asyncio
nest_asyncio.apply()

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = "8017395524:AAH8gY_CKKZU7hGJJOlX7WztOmQ7Q-J1V5U"
TARGET_CHANNEL_ID = "-1003107433425"  # or "@storebot1x"
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
{Colors.GREEN}    TELEGRAM BOT FILE PROCESSOR v12.0
    Download from ANY link | Extract | Send to Channel
    WITH PROGRESS BARS!
{Colors.CYAN}{'='*60}{Colors.END}
    """
    print(banner)

def ensure_directories():
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    EXTRACT_DIR.mkdir(exist_ok=True)

# ==================== PROGRESS BAR ====================
def create_progress_bar(percent: int, width: int = 20) -> str:
    """Create a text progress bar"""
    filled = int(width * percent / 100)
    bar = '█' * filled + '░' * (width - filled)
    return f"`[{bar}] {percent}%`"

async def update_progress(status_msg, current: int, total: int, stage: str, extra: str = ""):
    """Update progress message"""
    percent = int((current / total) * 100) if total > 0 else 0
    bar = create_progress_bar(percent)
    
    text = f"**{stage}**\n{bar}\n"
    if extra:
        text += f"{extra}\n"
    text += f"📊 Progress: {current}/{total}"
    
    try:
        await status_msg.edit_text(text, parse_mode='Markdown')
    except:
        pass

# ==================== DOWNLOAD FROM LINK WITH PROGRESS ====================
async def download_from_link(url: str, dest_path: Path, status_msg, file_name_hint: str = None) -> Tuple[bool, str, int]:
    """Download file from any direct link with progress bar"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, allow_redirects=True) as response:
                if response.status == 200:
                    # Get filename
                    filename = file_name_hint
                    if not filename:
                        if 'Content-Disposition' in response.headers:
                            cd = response.headers['Content-Disposition']
                            filename_match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', cd)
                            if filename_match:
                                filename = filename_match.group(1).strip('"\'')
                    
                    if not filename:
                        filename = url.split('/')[-1].split('?')[0]
                        if not filename or '.' not in filename:
                            filename = f"file_{int(time.time())}"
                    
                    total_size = int(response.headers.get('content-length', 0))
                    size_mb = total_size / (1024 * 1024)
                    
                    await update_progress(status_msg, 0, 100, "📥 Downloading", f"📁 {filename}\n💾 {size_mb:.1f} MB")
                    
                    # Download with progress
                    downloaded = 0
                    last_percent = 0
                    
                    with open(dest_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                                if percent >= last_percent + 2:
                                    last_percent = percent
                                    await update_progress(status_msg, percent, 100, "📥 Downloading", f"📁 {filename}\n💾 {size_mb:.1f} MB")
                    
                    await update_progress(status_msg, 100, 100, "✅ Download complete", f"📁 {filename}\n💾 {size_mb:.1f} MB")
                    return True, filename, total_size
                else:
                    await status_msg.edit_text(f"❌ **HTTP Error:** {response.status}")
                    return False, f"HTTP {response.status}", 0
                    
    except Exception as e:
        logger.error(f"Download error: {e}")
        await status_msg.edit_text(f"❌ **Download error:** {str(e)}")
        return False, str(e), 0

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

def extract_archive(file_path: Path, extract_to: Path, password: str = None, progress_callback=None) -> Tuple[bool, List[Path]]:
    try:
        archive_type = detect_archive_type(file_path)
        
        if not archive_type:
            logger.info(f"Not an archive: {file_path.name}")
            shutil.copy2(file_path, extract_to / file_path.name)
            if progress_callback:
                progress_callback(100, "File ready")
            return True, [extract_to / file_path.name]
        
        logger.info(f"Extracting {archive_type.upper()}: {file_path.name}")
        
        if archive_type == 'zip':
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                total = len(file_list)
                
                for idx, file_name in enumerate(file_list):
                    try:
                        if password:
                            zip_ref.extract(file_name, extract_to, pwd=password.encode())
                        else:
                            zip_ref.extract(file_name, extract_to)
                    except RuntimeError:
                        if password:
                            zip_ref.extract(file_name, extract_to)
                    
                    if progress_callback and idx % 5 == 0:
                        percent = int((idx + 1) / total * 100)
                        progress_callback(percent, f"Extracting: {file_name}")
                
                if progress_callback:
                    progress_callback(100, "Extraction complete")
                return True, list(extract_to.rglob("*"))
        
        elif archive_type in ['rar', '7z']:
            cmd = ['unar', '-o', str(extract_to), str(file_path)]
            if password:
                cmd.extend(['-p', password])
            
            if progress_callback:
                progress_callback(50, f"Extracting {archive_type.upper()}...")
            
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            if result.returncode == 0:
                if progress_callback:
                    progress_callback(100, "Extraction complete")
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

# ==================== SEND TO CHANNEL ====================
async def send_to_channel(bot: Bot, file_path: Path, caption: str, index: int, total: int, status_msg=None):
    """Send file to channel with progress"""
    try:
        if status_msg:
            percent = int(index / total * 100)
            bar = create_progress_bar(percent)
            await status_msg.edit_text(
                f"**📤 Uploading to channel**\n{bar}\n"
                f"Sending {index}/{total}: {file_path.name}",
                parse_mode='Markdown'
            )
        
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
async def process_and_send(bot: Bot, file_path: Path, password: str, file_name: str, status_msg) -> Dict:
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
        
        # Progress callback for extraction
        async def update_extract_progress(percent, message):
            bar = create_progress_bar(percent)
            await status_msg.edit_text(
                f"**📦 Extracting archive**\n{bar}\n"
                f"{message}\n"
                f"📁 {file_name}",
                parse_mode='Markdown'
            )
        
        # Create sync wrapper for progress callback
        def sync_progress_callback(percent, message):
            asyncio.create_task(update_extract_progress(percent, message))
        
        # Extract archive
        success, extracted_files = extract_archive(file_path, temp_extract, password, sync_progress_callback)
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
                success = await send_to_channel(bot, media_path, media_type, idx, len(media_files), status_msg)
                if success:
                    result['sent_media'] += 1
                else:
                    result['failed_media'] += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                result['failed_media'] += 1
                logger.error(f"Error sending {media_path.name}: {e}")
        
        shutil.rmtree(temp_extract, ignore_errors=True)
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Process error: {e}")
    
    return result

# ==================== TASK QUEUE ====================
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

# ==================== HANDLERS ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (links) and files"""
    user_id = update.effective_user.id
    
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("❌ Not authorized.")
        return
    
    # Check if it's a text message (link)
    if update.message.text:
        link = update.message.text.strip()
        
        # Check if it's a URL (http:// or https://)
        if link.startswith(('http://', 'https://')):
            await handle_link(update, context, link)
        else:
            await update.message.reply_text("❌ Please send a valid download link (http:// or https://) or upload a file.")
        return
    
    # Check if it's a document
    elif update.message.document:
        await handle_document(update, context)
        return
    
    # Check if it's a video
    elif update.message.video:
        await handle_video(update, context)
        return
    
    # Check if it's a photo
    elif update.message.photo:
        await handle_photo(update, context)
        return
    
    else:
        await update.message.reply_text("❌ Please send a download link or file.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE, link: str):
    """Handle download links"""
    status_msg = await update.message.reply_text(
        f"🔗 **Processing download link...**\n"
        f"`{link[:50]}...`\n\n"
        f"⏳ Connecting...",
        parse_mode='Markdown'
    )
    
    async def process():
        try:
            file_path = DOWNLOAD_DIR / f"temp_{int(time.time())}"
            
            # Download from link
            success, filename, filesize = await download_from_link(link, file_path, status_msg)
            
            if not success:
                return
            
            # Rename to proper filename
            final_path = DOWNLOAD_DIR / filename
            file_path.rename(final_path)
            
            # Process and send
            result = await process_and_send(
                context.bot,
                final_path,
                ZIP_PASSWORD,
                filename,
                status_msg
            )
            
            if result['error']:
                await status_msg.edit_text(
                    f"❌ **Failed:** {filename}\n"
                    f"Error: {result['error']}"
                )
            else:
                bar = create_progress_bar(100)
                await status_msg.edit_text(
                    f"✅ **COMPLETED!**\n\n"
                    f"{bar}\n"
                    f"📁 **File:** {filename}\n"
                    f"🎬 **Media sent:** {result['sent_media']}/{result['total_media']}\n"
                    f"🎯 **Target:** {TARGET_CHANNEL_ID}",
                    parse_mode='Markdown'
                )
            
            # Cleanup
            final_path.unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            await status_msg.edit_text(f"❌ **Error:** {str(e)}")
    
    await task_queue.add_task(process)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct file uploads"""
    doc = update.message.document
    file_name = doc.file_name
    file_size = doc.file_size
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
            file_path = DOWNLOAD_DIR / file_name
            
            await status_msg.edit_text(
                f"🔄 **Downloading:** {file_name}\n"
                f"💾 {size_mb:.1f} MB\n"
                f"📡 Using Telegram API..."
            )
            
            # Download file using bot API
            file = await context.bot.get_file(doc.file_id)
            await file.download_to_drive(file_path)
            
            await status_msg.edit_text(
                f"✅ **Downloaded:** {file_name}\n"
                f"🔄 Extracting media..."
            )
            
            # Process and send
            result = await process_and_send(
                context.bot,
                file_path,
                ZIP_PASSWORD,
                file_name,
                status_msg
            )
            
            if result['error']:
                await status_msg.edit_text(
                    f"❌ **Failed:** {file_name}\n"
                    f"Error: {result['error']}"
                )
            else:
                bar = create_progress_bar(100)
                await status_msg.edit_text(
                    f"✅ **COMPLETED!**\n\n"
                    f"{bar}\n"
                    f"📁 **File:** {file_name}\n"
                    f"🎬 **Media sent:** {result['sent_media']}/{result['total_media']}\n"
                    f"🎯 **Target:** {TARGET_CHANNEL_ID}",
                    parse_mode='Markdown'
                )
            
            file_path.unlink(missing_ok=True)
            
        except Exception as e:
            await status_msg.edit_text(f"❌ **Error:** {str(e)}")
    
    await task_queue.add_task(process)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct video uploads"""
    video = update.message.video
    file_name = video.file_name or f"video_{update.message.message_id}.mp4"
    
    status_msg = await update.message.reply_text(
        f"🎬 **Video queued:** {file_name}\n"
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
            await status_msg.edit_text(f"❌ **Failed:** {e}")
    
    await task_queue.add_task(process)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct photo uploads"""
    photo = update.message.photo[-1]
    
    status_msg = await update.message.reply_text(
        f"📸 **Photo queued**\nPosition: {task_queue.queue.qsize() + 1}",
        parse_mode='Markdown'
    )
    
    async def process():
        try:
            await status_msg.edit_text("📸 **Processing photo...**")
            
            file = await context.bot.get_file(photo.file_id)
            file_path = DOWNLOAD_DIR / f"photo_{int(time.time())}.jpg"
            await file.download_to_drive(file_path)
            
            with open(file_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=TARGET_CHANNEL_ID,
                    document=InputFile(f, filename=file_path.name),
                    caption=f"📸 Photo"
                )
            await status_msg.edit_text("✅ **Photo sent!**")
            
            file_path.unlink(missing_ok=True)
            
        except Exception as e:
            await status_msg.edit_text(f"❌ **Failed:** {e}")
    
    await task_queue.add_task(process)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 **Bot Ready!**\n\n"
        f"**I can handle:**\n"
        f"✅ **Download links:** Send any direct download link\n"
        f"✅ **Direct files:** Upload any file\n"
        f"✅ **Large files:** Up to 2GB supported\n\n"
        f"**Features:**\n"
        f"📊 **Progress bars** for download & extraction\n"
        f"🔄 **Queue system** for multiple files\n"
        f"📦 **Extracts:** ZIP, RAR, 7Z\n"
        f"🎬 **Sends:** Images & Videos\n\n"
        f"🎯 **Target:** `{TARGET_CHANNEL_ID}`\n"
        f"🔐 **Archive password:** `{ZIP_PASSWORD}`\n\n"
        f"Send me a link or file!",
        parse_mode='Markdown'
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    queue_size = task_queue.queue.qsize()
    await update.message.reply_text(
        f"📊 **Queue:** {queue_size} task(s) waiting",
        parse_mode='Markdown'
    )

# ==================== MAIN ====================
def main():
    print_banner()
    
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print(f"{Colors.FAIL}✗ Please add your bot token!{Colors.END}")
        return
    
    ensure_directories()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    
    print(f"{Colors.GREEN}✓ Bot started!{Colors.END}")
    print(f"{Colors.CYAN}✓ Progress bars enabled{Colors.END}")
    print(f"{Colors.CYAN}✓ Target channel: {TARGET_CHANNEL_ID}{Colors.END}")
    print(f"{Colors.GREEN}{'='*50}{Colors.END}")
    
    application.run_polling()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.GREEN}Bot stopped{Colors.END}")
        sys.exit(0)
