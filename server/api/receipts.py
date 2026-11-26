# -*- coding: utf-8 -*-
"""電子發票 API：取號 / 保存 / 作廢 / 列表。

**與合同鏈路完全獨立**：
- 不寫 `gens` 表（合同總表），合同管理列表與統計不受任何影響；
- 不走 docx 生成、不碰 /api/preview、不觸發 AI 複核；
- 純結構化資料落庫，出圖由前端 SVG → canvas PNG（3 倍圖）完成。

號段獨立於合同號：六位連續流水 000001…，與合同 `YYYYMMDD###` 互不干擾。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import store

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


class ReceiptPayload(BaseModel):
    no: str
    payer: str = ""
    purpose: str = ""
    amount: float = 0
    method: str = ""
    note: str = ""
    payee: str = ""
    receipt_date: str = ""
    sealed: bool = True


@router.post("/reserve")
def reserve():
    """開票頁面打開時占一個號（pending）。超時未保存自動回收。"""
    try:
        return {"no": store.reserve_receipt_no()}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:  # 資料庫鎖等：不吞錯，返回可讀原因
        raise HTTPException(status_code=500, detail=f"取號失敗：{e}")


@router.post("")
def save(p: ReceiptPayload):
    """保存發票（pending → ok）。同一號可重複保存以修正內容。"""
    try:
        return store.save_receipt(p.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{no}/release")
def release(no: str):
    """釋放尚未存檔的占號：切菜單 / 新開一張時呼叫，不必等 30 分鐘超時。

    已存檔的單不受影響（後端只刪 status='pending'）。
    """
    return {"no": no, "released": store.release_receipt(no)}


@router.post("/{no}/void")
def void(no: str):
    """作廢：留痕不刪，號不回收。"""
    if not store.void_receipt(no):
        raise HTTPException(status_code=400, detail="作廢失敗：編號不存在或已作廢")
    return {"no": no, "status": "void"}


@router.get("")
def lst(limit: int = 200):
    return {"items": store.list_receipts(limit)}
