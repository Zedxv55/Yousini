"""ทดสอบ Vision/Image input — base64 content block จริง (Phase 11)"""
import base64
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yousini_vision import content_with_images, is_image_path, IMG_TOKEN

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def test_is_image_path(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(PNG_1PX)
    assert is_image_path(str(img))
    assert not is_image_path(str(tmp_path / "note.txt"))
    (tmp_path / "noext").write_bytes(PNG_1PX)
    assert not is_image_path(str(tmp_path / "noext"))   # ไม่มีนามสกุล


def test_content_with_images_plain_text(tmp_path):
    c = content_with_images("สวัสดีไม่มีรูป", str(tmp_path))
    assert c == "สวัสดีไม่มีรูป"                          # ข้อความธรรมดา → str เดิม


def test_content_with_images_inline_path(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(PNG_1PX)
    c = content_with_images(f"ช่วยดู [img:{img}] แล้วบอกว่ามีอะไร", str(tmp_path))
    assert isinstance(c, list)
    imgs = [b for b in c if b["type"] == "image_url"]
    txts = [b for b in c if b["type"] == "text"]
    assert imgs and imgs[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert txts and "img:" not in txts[0]["text"]


def test_content_with_images_remove_placeholder(tmp_path):
    c = content_with_images("รูปว่างเปล่า [img:ไฟล์ที่ไม่มี.png]", str(tmp_path))
    assert c == "รูปว่างเปล่า"                            # ไม่มีไฟล์ → ตัด token ออกเท่านั้น


def test_content_with_images_http_url(tmp_path):
    c = content_with_images("ดู [img:https://example.com/x.png] สิ", str(tmp_path))
    assert isinstance(c, list)
    imgs = [b for b in c if b["type"] == "image_url"]
    assert imgs and imgs[0]["image_url"]["url"] == "https://example.com/x.png"


def test_max_images(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"img{i}.png"
        p.write_bytes(PNG_1PX)
        paths.append(p)
    text = " ".join(f"[img:{p}]" for p in paths)
    c = content_with_images(text, str(tmp_path))
    imgs = [b for b in c if b["type"] == "image_url"]
    assert len(imgs) == 3                                # จำกัด 3 รูปต่อข้อความ