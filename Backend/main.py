import os
import json
import time
from fastapi import FastAPI, HTTPException, Form, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional, List

load_dotenv()

app = FastAPI()

# ============================================================
# 1. CẤU HÌNH CORS
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 2. KẾT NỐI SUPABASE
# ============================================================
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# ============================================================
# 3. ĐƯỜNG DẪN THƯ MỤC
# ============================================================
CURRENT_DIR  = os.path.dirname(os.path.abspath(__file__))
BASE_DIR     = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
FRONTEND_DIR = os.path.join(BASE_DIR, "Frontend")

# Phục vụ file tĩnh (style.css, ảnh...) tại /assets
app.mount(
    "/assets",
    StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")),
    name="assets",
)


# ============================================================
# PHẦN 1: TRẢ VỀ CÁC TRANG HTML
# ============================================================

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/main")
async def read_main():
    return FileResponse(os.path.join(FRONTEND_DIR, "main.html"))

@app.get("/create")
async def read_create():
    return FileResponse(os.path.join(FRONTEND_DIR, "create.html"))

@app.get("/chat")
async def read_chat():
    return FileResponse(os.path.join(FRONTEND_DIR, "chat.html"))

@app.get("/profile")
async def read_profile():
    return FileResponse(os.path.join(FRONTEND_DIR, "profile.html"))

@app.get("/reset-password")
async def read_reset():
    return FileResponse(os.path.join(FRONTEND_DIR, "reset-password.html"))


# ============================================================
# PHẦN 2: API NHÓM (/api/groups)
# ============================================================

# GET /api/groups — Lấy tất cả nhóm
@app.get("/api/groups")
async def get_all_groups():
    response = supabase.table("groups").select("*").order("created_at", desc=True).execute()
    return response.data


# GET /api/groups/search?keyword=...&tag=...
# ⚠️ Phải đặt TRƯỚC /api/groups/{group_id} không bị FastAPI hiểu nhầm
@app.get("/api/groups/search")
async def search_groups(keyword: str = "", tag: str = ""):
    query = supabase.table("groups").select("*")
    if keyword:
        query = query.ilike("name", f"%{keyword}%")
    response = query.execute()
    results = response.data
    if tag and results:
        results = [g for g in results if tag in (g.get("tags") or [])]
    return results


# GET /api/groups/{group_id} — Lấy thông tin 1 nhóm
@app.get("/api/groups/{group_id}")
async def get_group(group_id: str):
    response = supabase.table("groups").select("*").eq("id", group_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
    return response.data[0]


# POST /api/groups — Tạo nhóm mới
# Nhận FormData + file ảnh từ create.html
@app.post("/api/groups")
async def create_group(
    name:        str           = Form(...),
    description: str           = Form(...),
    maxMember:   int           = Form(...),
    privacy:     str           = Form(...),
    tags:        str           = Form(...),    # JSON string, vd: '["AI","gym"]'
    image:       UploadFile    = File(None),   # Ảnh bìa sau khi crop (không bắt buộc)
    created_by:  Optional[str] = Form(None),   # User ID người tạo
):
    # --- Kiểm tra dữ liệu hợp lệ ---
    if not name or not description:
        raise HTTPException(status_code=400, detail="Thiếu tên hoặc mô tả nhóm")
    if maxMember < 1 or maxMember > 50:
        raise HTTPException(status_code=400, detail="Số thành viên phải từ 1 đến 50")
    if privacy not in ["public", "private"]:
        raise HTTPException(status_code=400, detail="Privacy phải là 'public' hoặc 'private'")

    # --- Parse tags từ JSON string sang list Python ---
    try:
        tags_list = json.loads(tags)
    except Exception:
        tags_list = []
    if len(tags_list) > 5:
        raise HTTPException(status_code=400, detail="Tối đa 5 tag")

    # --- Upload ảnh bìa lên Supabase Storage ---
    # FIX: create.html luôn gửi file tên "cover.jpg" (do dùng croppedBlob).
    # Nếu dùng tên đó thẳng thì các nhóm sẽ ghi đè ảnh lên nhau.
    # Giải pháp: đặt tên file = tên_nhóm + timestamp → đảm bảo luôn unique.
    image_url = None
    if image and image.filename:
        try:
            file_bytes = await image.read()
            safe_name  = name.replace(" ", "_").lower()          # vd: "nhom_ai"
            timestamp  = int(time.time())                        # vd: 1717000000
            file_path  = f"covers/{safe_name}_{timestamp}.jpg"  # vd: "covers/nhom_ai_1717000000.jpg"

            supabase.storage.from_("group-images").upload(
                file_path,
                file_bytes,
                {"content-type": "image/jpeg"},
            )

            image_url = supabase.storage.from_("group-images").get_public_url(file_path)
        except Exception as e:
            # Lỗi upload ảnh thì vẫn tạo nhóm được, chỉ không có ảnh bìa
            print(f"[WARN] Lỗi upload ảnh bìa: {e}")
            image_url = None

    # --- Lưu nhóm vào database ---
    new_group = {
        "name":        name,
        "description": description,
        "max_members": maxMember,
        "privacy":     privacy,
        "tags":        tags_list,
        "image_url":   image_url,   # Khớp với tên cột main.html đang dùng
        "created_by":  created_by,
    }
    response = supabase.table("groups").insert(new_group).execute()
    return {"message": "Tạo nhóm thành công!", "data": response.data}


# DELETE /api/groups/{group_id} — Xóa nhóm
@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: str):
    supabase.table("groups").delete().eq("id", group_id).execute()
    return {"message": "Đã xóa nhóm"}


# ============================================================
# PHẦN 3: API TIN NHẮN (/api/messages)
# Lưu ý: chat.html hiện tại gọi Supabase trực tiếp, không qua API này.
# API vẫn giữ lại để dùng nếu cần thêm logic phía server sau này.
# ============================================================

class MessageSend(BaseModel):
    group_id: str
    sender_id: str
    sender_name: str
    content: str


# GET /api/messages/{group_id} — Lấy lịch sử chat của 1 nhóm
@app.get("/api/messages/{group_id}")
async def get_messages(group_id: str, limit: int = 50):
    response = (
        supabase.table("messages")
        .select("*")
        .eq("group_id", group_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return response.data


# POST /api/messages — Gửi tin nhắn mới
@app.post("/api/messages")
async def send_message(msg: MessageSend):
    if not msg.content.strip():
        raise HTTPException(status_code=400, detail="Tin nhắn không được trống")
    new_message = {
        "group_id":    msg.group_id,
        "sender_id":   msg.sender_id,
        "sender_name": msg.sender_name,
        "content":     msg.content.strip(),
    }
    response = supabase.table("messages").insert(new_message).execute()
    return {"message": "Gửi thành công", "data": response.data}


# ============================================================
# PHẦN 4: API THÀNH VIÊN NHÓM (/api/groups/{id}/members)
# ============================================================

# GET /api/groups/{group_id}/members — Xem danh sách thành viên
@app.get("/api/groups/{group_id}/members")
async def get_members(group_id: str):
    response = (
        supabase.table("group_members")
        .select("*")
        .eq("group_id", group_id)
        .execute()
    )
    return response.data


# POST /api/groups/{group_id}/join — Tham gia nhóm
@app.post("/api/groups/{group_id}/join")
async def join_group(group_id: str, user_id: str):
    group_res = supabase.table("groups").select("*").eq("id", group_id).execute()
    if not group_res.data:
        raise HTTPException(status_code=404, detail="Nhóm không tồn tại")

    existing = (
        supabase.table("group_members")
        .select("*")
        .eq("group_id", group_id)
        .eq("user_id", user_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=400, detail="Bạn đã là thành viên nhóm này rồi")

    supabase.table("group_members").insert({
        "group_id": group_id,
        "user_id":  user_id,
    }).execute()
    return {"message": "Tham gia nhóm thành công!"}


# POST /api/groups/{group_id}/leave — Rời nhóm
@app.post("/api/groups/{group_id}/leave")
async def leave_group(group_id: str, user_id: str):
    supabase.table("group_members").delete() \
        .eq("group_id", group_id) \
        .eq("user_id", user_id) \
        .execute()
    return {"message": "Đã rời nhóm"}
