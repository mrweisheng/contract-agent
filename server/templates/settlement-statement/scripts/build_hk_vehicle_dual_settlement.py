from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

OUT = "/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv/output/pdf/港車買賣結算單雙幣版預覽.pdf"
LOGO = "/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv/assets/ming-ge-cross-border-logo-v1.png"
pdfmetrics.registerFont(TTFont("CJK", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))

W, H = letter
NAVY = HexColor("#0B2E59"); RMB = HexColor("#EAF3FA"); HKD = HexColor("#F4F8FC")
TEXT = HexColor("#1D2733"); GRAY = HexColor("#687386"); BORDER = HexColor("#CBD8E5")
c = canvas.Canvas(OUT, pagesize=letter); c.setTitle("港車買賣結算單雙幣版")

def txt(x,y,s,size=9,color=TEXT,align="left",bold=False):
    c.setFillColor(color); c.setFont("CJK", size+(0.55 if bold else 0))
    if align=="center": c.drawCentredString(x,y,s)
    elif align=="right": c.drawRightString(x,y,s)
    else: c.drawString(x,y,s)

def box(x,top,w,h,fill=white):
    c.setFillColor(fill); c.setStrokeColor(BORDER); c.setLineWidth(0.6); c.rect(x,top-h,w,h,fill=1,stroke=1)

def cell(x,top,w,h,s,fill=white,color=TEXT,align="left",size=8.3,bold=False,pad=7):
    box(x,top,w,h,fill); px=x+pad if align=="left" else (x+w/2 if align=="center" else x+w-pad)
    txt(px,top-h/2-3,s,size,color,align,bold)

# Header
c.drawImage(ImageReader(LOGO),45,690,width=195,height=78,preserveAspectRatio=True,mask="auto")
txt(565,748,"VEHICLE SETTLEMENT STATEMENT",9.2,GRAY,"right",True)
txt(565,714,"港車買賣結算單",21,NAVY,"right",True)
txt(565,681,"日期  2026年9月21日",8.5,GRAY,"right")

x0, top = 45,655; mw=[78,180,78,186]
meta=[["客戶名稱","[客戶名稱]","群名","[業務群名稱]"],
      ["購買車輛","[車輛品牌／型號／車牌]","結算類型","[車款／手續費／尾款／雜費]"]]
for r,row in enumerate(meta):
    x=x0
    for i,s in enumerate(row):
        label=i in (0,2); cell(x,top-r*29,mw[i],29,s,NAVY if label else white,white if label else TEXT,"center" if label else "left",9.1,label); x+=mw[i]

# Detail table
table_top=580; seq_w,item_w,due_w=34,168,90; digit_w=28.75
cell(x0,table_top,seq_w,38,"序號",NAVY,white,"center",10.2,True)
cell(x0+seq_w,table_top,item_w,38,"收款項目",NAVY,white,"center",10.5,True)
cell(x0+seq_w+item_w,table_top,due_w,38,"應收金額",NAVY,white,"center",10.5,True)
dx=x0+seq_w+item_w+due_w; box(dx,table_top,digit_w*8,18,NAVY); txt(dx+digit_w*4,table_top-13,"金額",10.5,white,"center",True)
for i,lab in enumerate(["十萬","萬","千","百","十","元","角","分"]): cell(dx+i*digit_w,table_top-18,digit_w,20,lab,NAVY,white,"center",8.8,True,1)

def group(y,label,fill,color=NAVY): cell(x0,y,522,19,label,fill,color,"left",9.2,True,10)
def row(y,no,item,amount,fill):
    cell(x0,y,seq_w,25,str(no),fill,TEXT,"center",9.1); cell(x0+seq_w,y,item_w,25,item,fill,TEXT,"left",8.8)
    cell(x0+seq_w+item_w,y,due_w,25,amount,fill,TEXT,"center",9.2)
    for i in range(8): cell(dx+i*digit_w,y,digit_w,25,"",fill)

y=table_top-38; group(y,"人民幣 CNY",RMB); y-=19
for data in [(1,"換車／過戶手續費","¥ 0.00"),(2,"境內服務或代辦費","¥ 0.00"),(3,"其他增加或減少項","¥ 0.00")]: row(y,*data,RMB); y-=25
group(y,"港幣 HKD",HKD); y-=19
for data in [(4,"車輛成交價","$ 0.00"),(5,"訂金或前期已付款","$ 0.00"),(6,"驗車／維修／運輸費用","$ 0.00"),(7,"其他增加或減少項","$ 0.00")]: row(y,*data,HKD); y-=25

cell(x0,y,522,29,"備註：",white,NAVY,"left",9.5,True,9); y-=29
box(x0,y,522,36,NAVY); txt(x0+12,y-24,"本次應收總額：",12,white,"left",True); txt(x0+165,y-24,"¥",13,white,"left",True); txt(x0+318,y-24,"/",13,white,"center",True); txt(x0+360,y-24,"$",13,white,"left",True); y-=36
txt(x0,y-16,"金額說明",8.8,NAVY,"left",True)
txt(x0+52,y-16,"人民幣與港幣分開核算。正數表示新增應收，負數表示已付款、退款、優惠或扣減。",7.5,TEXT); y-=30

# Both receiving accounts
lx,rx=x0,x0+261; lw,vw=83,178; rh=22
mainland=[("大陸收款帳戶","陳振耀"),("開戶銀行","工商銀行"),("收款帳號","2009020501023937427"),("網點號","0205"),("名稱","汕尾海豐東門頭支行"),("地址","海豐縣城人民中路7號"),("電話","0660-6623712")]
hk=[("香港收款帳戶","華星資源開發有限公司"),("英文名稱","CHINA STAR RESOURCE DEVELOPMENT LIMITED"),("開戶銀行","華僑銀行"),("收款帳號","035-802-129-690-051"),("轉數快識別碼","131-831-406")]
for i,(lab,val) in enumerate(mainland): cell(lx,y-i*rh,lw,rh,lab,RMB,NAVY,"center",7.2,True,2); cell(lx+lw,y-i*rh,vw,rh,val,white,TEXT,"left",7.2,False,6)
for i,(lab,val) in enumerate(hk):
    cell(rx,y-i*rh,lw,rh,lab,RMB,NAVY,"center",7.0,True,2); cell(rx+lw,y-i*rh,vw,rh,val,white,TEXT,"left",6.4 if i==1 else 7.1,False,5)

txt(W/2,35,"明哥中港牌  MING GE CROSS BORDER",8,GRAY,"center")
c.showPage(); c.save(); print(OUT)
