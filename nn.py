import os
import shutil
from pyrogram import Client, filters
import patoolib

# ================= CONFIG =================

API_ID = 24444776
API_HASH = "f04986e0cbd332b2b2e6350f314f49b0"
BOT_TOKEN = "8306437248:AAH6Y8QNOgoFQJtPN7joFGOsliEBuhTkDEM"

CHANNEL_ID = "@storebot1x"  # CHANGE THIS

PASSWORDS = ["cosplaytele"]

DOWNLOAD_PATH = "downloads/"
EXTRACT_PATH = "extracted/"

# ==========================================

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(EXTRACT_PATH, exist_ok=True)

app = Client(
    "extractor_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ========= COMMANDS ========= #

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply(
        "👋 **Welcome!**\n\n"
        "📦 Send RAR/ZIP file\n"
        "🔓 Auto extract with passwords\n\n"
        "📤 Output:\n"
        "🖼 Images → Document (HD)\n"
        "🎬 Videos → Video Player\n"
    )

# ========= MAIN ========= #

@app.on_message(filters.document)
async def handle_file(client, message):
    msg = await message.reply("📥 Downloading...")

    try:
        file_path = await message.download(file_name=DOWNLOAD_PATH)
    except Exception as e:
        await msg.edit(f"❌ Download failed:\n`{e}`")
        return

    await msg.edit("📦 Extracting archive...")

    extracted = False
    used_password = None

    for pwd in PASSWORDS:
        try:
            patoolib.extract_archive(
                file_path,
                outdir=EXTRACT_PATH,
                password=pwd
            )
            extracted = True
            used_password = pwd
            break
        except:
            continue

    if not extracted:
        await msg.edit("❌ Extraction failed!\nPassword not matched.")
        return

    await msg.edit(f"🔓 Password used: `{used_password}`\n📤 Uploading...")

    img_count = 0
    vid_count = 0

    # SORT FILES (important for order)
    all_files = []
    for root, dirs, files in os.walk(EXTRACT_PATH):
        for file in files:
            all_files.append(os.path.join(root, file))

    all_files.sort()

    for full_path in all_files:
        file = os.path.basename(full_path)

        try:
            # 🖼 Images → DOCUMENT
            if file.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                await client.send_document(
                    CHANNEL_ID,
                    full_path,
                    caption=f"🖼 {file}"
                )
                img_count += 1

            # 🎬 Videos → VIDEO
            elif file.lower().endswith((".mp4", ".mkv")):
                await client.send_video(
                    CHANNEL_ID,
                    full_path,
                    caption=f"🎬 {file}"
                )
                vid_count += 1

        except Exception as e:
            print(f"Upload error: {e}")

    await msg.edit(
        "✅ **Upload Completed!**\n\n"
        f"🖼 Images: {img_count}\n"
        f"🎬 Videos: {vid_count}"
    )

    # Cleanup
    try:
        shutil.rmtree(EXTRACT_PATH)
        os.makedirs(EXTRACT_PATH)
    except:
        pass

app.run()
