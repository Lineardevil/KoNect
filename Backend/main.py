import os
import json
import time
from fastapi import FastAPI, HTTPException, Form, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional, List

# Đọc file .env (chỉ có tác dụng ở máy local, trên Vercel dùng Environment Variables)
load_dotenv()

app = FastAPI()

# ============================================================
# 1. CẤU HÌNH CORS
# Cho phép trình duyệt ở bất kỳ domain nào gọi API của backend.
# Cần thiết vì frontend và backend có thể chạy ở địa chỉ khác nhau.
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 2. KẾT NỐI SUPABASE
# Đọc URL và KEY từ biến môi trường (không hardcode vào code).
# Bọc trong try/except để server không crash nếu chưa set biến.
# ============================================================
supabase: Optional[Client] = None
try:
    _url = os.environ.get("SUPABASE_URL")
    _key = os.environ.get("SUPABASE_KEY")
    if _url and _key:
        supabase = create_client(_url, _key)
    else:
        print("[ERROR] Thiếu SUPABASE_URL hoặc SUPABASE_KEY!")
except Exception as e:
    print(f"[ERROR] Không kết nối được Supabase: {e}")


def get_supabase() -> Client:
    """
    Hàm tiện ích: trả về Supabase client.
    Nếu chưa kết nối thì báo lỗi rõ ràng thay vì crash im lặng.
    """
    if supabase is None:
        raise HTTPException(
            status_code=503,
            detail="Chưa cấu hình SUPABASE_URL / SUPABASE_KEY. Kiểm tra Environment Variables trên Vercel."
        )
    return supabase


# ============================================================
# 3. ĐƯỜNG DẪN THƯ MỤC
# __file__ = vị trí của file main.py này (trong thư mục backend/)
# Lùi ra 1 cấp để lấy thư mục gốc, rồi trỏ vào thư mục Frontend/
# ============================================================
CURRENT_DIR  = os.path.dirname(os.path.abspath(__file__))       # .../backend/
BASE_DIR     = os.path.abspath(os.path.join(CURRENT_DIR, "..")) # .../KNNN/
FRONTEND_DIR = os.path.join(BASE_DIR, "Frontend")               # .../KNNN/Frontend/
ASSETS_DIR   = os.path.join(FRONTEND_DIR, "assets")             # .../KNNN/Frontend/assets/

# Mount thư mục assets để trình duyệt load được style.css, ảnh, v.v.
# Bọc trong try/except vì trên Vercel đường dẫn có thể khác máy local.
try:
    if os.path.isdir(ASSETS_DIR):
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
        print(f"[OK] Static files: {ASSETS_DIR}")
    else:
        print(f"[WARN] Không tìm thấy assets tại: {ASSETS_DIR}")
except Exception as e:
    print(f"[WARN] Không mount được static files: {e}")


# ============================================================
# PHẦN 1: TRẢ VỀ CÁC TRANG HTML
# Khi trình duyệt vào /main, /chat, v.v., backend trả về file HTML tương ứng.
# Hàm serve_html() kiểm tra file tồn tại không trước khi trả về.
# ============================================================

def serve_html(filename: str):
    path = os.path.join(FRONTEND_DIR, filename)
    if not os.path.isfile(path):
        return JSONResponse(
            status_code=404,
            content={"error": f"Không tìm thấy {filename}", "FRONTEND_DIR": FRONTEND_DIR}
        )
    return FileResponse(path)

@app.get("/")
async def read_index():
    return serve_html("index.html")

@app.get("/main")
async def read_main():
    return serve_html("main.html")

@app.get("/create")
async def read_create():
    return serve_html("create.html")

@app.get("/chat")
async def read_chat():
    return serve_html("chat.html")

@app.get("/profile")
async def read_profile():
    return serve_html("profile.html")

@app.get("/reset-password")
async def read_reset():
    return serve_html("reset-password.html")


# ============================================================
# PHẦN 2: API NHÓM (/api/groups)
# Các endpoint để tạo, tìm kiếm, xem, xóa nhóm.
# Dữ liệu lưu trong bảng "groups" trên Supabase.
# ============================================================

# GET /api/groups
# Trả về toàn bộ danh sách nhóm, mới nhất lên trên.
@app.get("/api/groups")
async def get_all_groups():
    db = get_supabase()
    response = db.table("groups").select("*").order("created_at", desc=True).execute()
    return response.data


# GET /api/groups/search?keyword=abc&tag=AI
# Tìm nhóm theo tên (keyword) hoặc tag.
# ⚠️ PHẢI đặt route này TRƯỚC /api/groups/{group_id}
#    vì nếu không, FastAPI sẽ hiểu "search" là một group_id.
@app.get("/api/groups/search")
async def search_groups(keyword: str = "", tag: str = ""):
    db = get_supabase()
    query = db.table("groups").select("*")
    if keyword:
        # ilike = tìm kiếm không phân biệt hoa thường
        query = query.ilike("name", f"%{keyword}%")
    response = query.execute()
    results = response.data
    # Lọc tag trong Python vì Supabase không lọc mảng trực tiếp dễ dàng
    if tag and results:
        results = [g for g in results if tag in (g.get("tags") or [])]
    return results


# GET /api/groups/{group_id}
# Lấy thông tin chi tiết của 1 nhóm theo ID.
@app.get("/api/groups/{group_id}")
async def get_group(group_id: str):
    db = get_supabase()
    response = db.table("groups").select("*").eq("id", group_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
    return response.data[0]


# POST /api/groups
# Tạo nhóm mới. Nhận FormData (không phải JSON) vì có kèm file ảnh.
# create.html gửi: name, description, maxMember, privacy, tags (JSON string), image (file).
@app.post("/api/groups")
async def create_group(
    name:        str           = Form(...),       # Bắt buộc
    description: str           = Form(...),       # Bắt buộc
    maxMember:   int           = Form(...),       # Bắt buộc
    privacy:     str           = Form(...),       # "public" hoặc "private"
    tags:        str           = Form(...),       # Chuỗi JSON, vd: '["AI","gym"]'
    image:       UploadFile    = File(None),      # File ảnh (không bắt buộc)
    created_by:  Optional[str] = Form(None),      # User ID người tạo
):
    db = get_supabase()

    # Kiểm tra dữ liệu đầu vào
    if not name or not description:
        raise HTTPException(status_code=400, detail="Thiếu tên hoặc mô tả nhóm")
    if maxMember < 1 or maxMember > 50:
        raise HTTPException(status_code=400, detail="Số thành viên phải từ 1 đến 50")
    if privacy not in ["public", "private"]:
        raise HTTPException(status_code=400, detail="Privacy phải là 'public' hoặc 'private'")

    # Chuyển tags từ chuỗi JSON sang list Python
    try:
        tags_list = json.loads(tags)
    except Exception:
        tags_list = []
    if len(tags_list) > 5:
        raise HTTPException(status_code=400, detail="Tối đa 5 tag")

    # Upload ảnh bìa lên Supabase Storage (bucket "group-images")
    # create.html luôn gửi file tên "cover.jpg" (do dùng Cropper → blob).
    # Dùng timestamp để tạo tên file unique, tránh các nhóm ghi đè ảnh nhau.
    image_url = None
    if image and image.filename:
        try:
            file_bytes = await image.read()
            safe_name  = name.replace(" ", "_").lower()         # "Nhóm AI" → "nhóm_ai"
            timestamp  = int(time.time())                       # vd: 1717000000
            file_path  = f"covers/{safe_name}_{timestamp}.jpg" # vd: "covers/nhóm_ai_1717000000.jpg"

            db.storage.from_("group-images").upload(
                file_path,
                file_bytes,
                {"content-type": "image/jpeg"},
            )
            # Lấy URL công khai để lưu vào database và hiển thị trên main.html
            image_url = db.storage.from_("group-images").get_public_url(file_path)
        except Exception as e:
            # Lỗi upload ảnh thì vẫn tạo nhóm được, chỉ không có ảnh bìa
            print(f"[WARN] Lỗi upload ảnh bìa: {e}")
            image_url = None

    # Lưu nhóm vào database
    new_group = {
        "name":        name,
        "description": description,
        "max_members": maxMember,
        "privacy":     privacy,
        "tags":        tags_list,
        "image_url":   image_url,  # Tên cột phải khớp với bảng "groups" trên Supabase
        "created_by":  created_by,
    }
    response = db.table("groups").insert(new_group).execute()
    return {"message": "Tạo nhóm thành công!", "data": response.data}


# DELETE /api/groups/{group_id}
# Xóa nhóm theo ID.
@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: str):
    db = get_supabase()
    db.table("groups").delete().eq("id", group_id).execute()
    return {"message": "Đã xóa nhóm"}


# ============================================================
# PHẦN 3: API TIN NHẮN (/api/messages)
# Lưu ý: chat.html hiện tại gọi Supabase JS trực tiếp từ trình duyệt,
# không đi qua backend. Các API này giữ lại để dùng sau nếu cần.
# ============================================================

class MessageSend(BaseModel):
    group_id: str
    sender_id: str
    sender_name: str
    content: str


# GET /api/messages/{group_id}
# Lấy lịch sử tin nhắn của 1 nhóm (50 tin gần nhất).
@app.get("/api/messages/{group_id}")
async def get_messages(group_id: str, limit: int = 50):
    db = get_supabase()
    response = (
        db.table("messages")
        .select("*")
        .eq("group_id", group_id)
        .order("created_at", desc=False)  # Cũ nhất lên trên
        .limit(limit)
        .execute()
    )
    return response.data


# POST /api/messages
# Gửi tin nhắn mới vào 1 nhóm.
@app.post("/api/messages")
async def send_message(msg: MessageSend):
    db = get_supabase()
    if not msg.content.strip():
        raise HTTPException(status_code=400, detail="Tin nhắn không được trống")
    new_message = {
        "group_id":    msg.group_id,
        "sender_id":   msg.sender_id,
        "sender_name": msg.sender_name,
        "content":     msg.content.strip(),
    }
    response = db.table("messages").insert(new_message).execute()
    return {"message": "Gửi thành công", "data": response.data}


# ============================================================
# PHẦN 4: API THÀNH VIÊN NHÓM (/api/groups/{id}/members)
# ============================================================

# GET /api/groups/{group_id}/members
# Lấy danh sách thành viên của 1 nhóm.
@app.get("/api/groups/{group_id}/members")
async def get_members(group_id: str):
    db = get_supabase()
    response = (
        db.table("group_members")
        .select("*")
        .eq("group_id", group_id)
        .execute()
    )
    return response.data


# POST /api/groups/{group_id}/join
# Tham gia nhóm. Kiểm tra nhóm tồn tại và chưa là thành viên.
@app.post("/api/groups/{group_id}/join")
async def join_group(group_id: str, user_id: str):
    db = get_supabase()
    group_res = db.table("groups").select("*").eq("id", group_id).execute()
    if not group_res.data:
        raise HTTPException(status_code=404, detail="Nhóm không tồn tại")

    existing = (
        db.table("group_members")
        .select("*")
        .eq("group_id", group_id)
        .eq("user_id", user_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=400, detail="Bạn đã là thành viên nhóm này rồi")

    db.table("group_members").insert({
        "group_id": group_id,
        "user_id":  user_id,
    }).execute()
    return {"message": "Tham gia nhóm thành công!"}


# POST /api/groups/{group_id}/leave
# Rời khỏi nhóm.
@app.post("/api/groups/{group_id}/leave")
async def leave_group(group_id: str, user_id: str):
    db = get_supabase()
    db.table("group_members").delete() \
        .eq("group_id", group_id) \
        .eq("user_id", user_id) \
        .execute()
    return {"message": "Đã rời nhóm"}
