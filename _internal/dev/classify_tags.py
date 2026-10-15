# -*- coding: utf-8 -*-
"""把「一级/二级分类」整理进 tagsd_danbooru_zh.csv：

  1) 二级合并：老的 89 个 (一级, 二级) 桶 -> 新结构（12 个一级、最多 15 个二级）
  2) 规则分类：给**热度前 N 名**里还没分类的实用词条（人物 / 构图取景 / 背景 / 物件 / 元标签 / 画面 / R18）
     自动填一级 + 二级；画师 / 角色 / 作品名（danbooru category 1/3/4）**不铺**，留给后面按需处理
  3) 只填空格子 + 合并映射幂等，可以反复运行

用法:
    python _internal/dev/classify_tags.py --dry-run            # 只看报告，不写文件
    python _internal/dev/classify_tags.py                      # 前 20000 名
    python _internal/dev/classify_tags.py --limit-rank 50000
    python _internal/dev/classify_tags.py --merge-only         # 只做二级合并

改 CSV 前会自动备份成 tagsd_danbooru_zh.csv.prefill.bak（已存在则不覆盖）。
"""
import collections
import csv
import io
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV = os.path.join(ROOT, "_internal", "data", "tagsd_danbooru_zh.csv")
BACKUP = CSV + ".prefill.bak"
REPORT_DIR = os.path.join(ROOT, "_internal", "dev", "reports")

# ---------------------------------------------------------------- 二级合并映射
# (旧一级, 旧二级) -> (新一级, 新二级)；没列到的 (一级, 二级) 原样保留（幂等）
MERGE = [
    # kontext 指令：5 -> 2
    ("kontext指令", "全局编辑", "kontext指令", "编辑指令"),
    ("kontext指令", "局部编辑", "kontext指令", "编辑指令"),
    ("kontext指令", "文字编辑", "kontext指令", "编辑指令"),
    ("kontext指令", "角色参考", "kontext指令", "参考图"),
    ("kontext指令", "风格参考", "kontext指令", "参考图"),
    # 人物：服装 / 配饰
    ("人物", "服装", "人物", "服装"),
    ("人物", "上装", "人物", "服装"),
    ("人物", "下装", "人物", "服装"),
    ("人物", "其他服装", "人物", "服装"),
    ("人物", "袜类", "人物", "配饰"),
    ("人物", "鞋类", "人物", "配饰"),
    ("人物", "帽饰", "人物", "配饰"),
    ("人物", "首饰", "人物", "配饰"),
    ("人物", "发饰", "人物", "配饰"),
    ("人物", "装饰", "人物", "配饰"),
    # 人物：头发
    ("人物", "发型，其他", "人物", "发型"),
    ("人物", "发型，前发", "人物", "发型"),
    ("人物", "发型，双马尾", "人物", "发型"),
    ("人物", "发型，种类", "人物", "发型"),
    ("人物", "发型，长度", "人物", "发型"),
    ("人物", "发型，马尾", "人物", "发型"),
    ("人物", "发色", "人物", "发色"),
    ("人物", "发色，单色", "人物", "发色"),
    ("人物", "发色，多色", "人物", "发色"),
    # 人物：五官 / 表情
    ("人物", "眼睛", "人物", "五官"),
    ("人物", "嘴巴", "人物", "五官"),
    ("人物", "眉毛", "人物", "五官"),
    ("人物", "胡子&牙", "人物", "五官"),
    ("人物", "表情", "人物", "表情"),
    # 人物：体貌
    ("人物", "胸", "人物", "体貌特征"),
    ("人物", "尾巴", "人物", "体貌特征"),
    ("人物", "角", "人物", "体貌特征"),
    ("人物", "翅膀", "人物", "体貌特征"),
    ("人物", "年龄", "人物", "体形与肤色"),
    ("人物", "体形", "人物", "体形与肤色"),
    ("人物", "肤色", "人物", "体形与肤色"),
    ("人物", "皮肤性质", "人物", "体形与肤色"),
    ("人物", "身体部位", "人物", "体形与肤色"),
    # 人物：动作 / 对象 / 其他
    ("人物", "姿态", "人物", "姿势动作"),
    ("人物", "手势", "人物", "姿势动作"),
    ("人物", "视线", "人物", "姿势动作"),
    ("人物", "对象", "人物", "对象与数量"),
    ("人物", "数量", "人物", "对象与数量"),
    ("人物", "职业", "人物", "职业"),
    ("人物", "性行为", "人物", "性行为"),
    ("人物", "风格", "画面", "艺术风格"),
    ("人物", "动漫", "画面", "艺术风格"),
    ("人物", "??", "人物", "其他"),
    # 人物：汉服（唐/宋/明 -> 汉服）
    ("人物", "唐风，上衫", "人物", "汉服"),
    ("人物", "唐风，披帛，霞帔", "人物", "汉服"),
    ("人物", "唐风，系带", "人物", "汉服"),
    ("人物", "唐风，长上衫", "人物", "汉服"),
    ("人物", "唐风，齐胸褶裙", "人物", "汉服"),
    ("人物", "唐风，齐胸襦裙", "人物", "汉服"),
    ("人物", "宋风，宋抹", "人物", "汉服"),
    ("人物", "宋风，百褶裙", "人物", "汉服"),
    ("人物", "宋风，短衫", "人物", "汉服"),
    ("人物", "宋风，装饰", "人物", "汉服"),
    ("人物", "宋风，裙子", "人物", "汉服"),
    ("人物", "宋风，长衫", "人物", "汉服"),
    ("人物", "宋风，领子", "人物", "汉服"),
    ("人物", "明风，上衣", "人物", "汉服"),
    # 取景（整体/上下半身）搬到新一级「构图取景」
    ("人物", "整体", "构图取景", "构图"),
    ("人物", "上半身", "构图取景", "构图"),
    ("人物", "下半身", "构图取景", "构图"),
    # 画面：拆成 画质 / 光照 / 艺术风格 / 装饰，场景与氛围归「背景」，视角归「构图取景」
    ("画面", "1画质", "画面", "画质"),
    ("画面", "光照", "画面", "光照"),
    ("画面", "艺术家风格", "画面", "艺术风格"),
    ("画面", "艺术派系", "画面", "艺术风格"),
    ("画面", "艺术类型", "画面", "艺术风格"),
    ("画面", "艺术风格", "画面", "艺术风格"),
    ("画面", "装饰", "画面", "装饰"),
    ("画面", "四季朝暮", "背景", "氛围"),
    ("画面", "天涯海角", "背景", "氛围"),
    ("画面", "日月星辰", "背景", "氛围"),
    ("画面", "背景氛围", "背景", "氛围"),
    ("画面", "城市建筑", "背景", "场景"),
    ("画面", "室内场景", "背景", "场景"),
    ("画面", "视线", "构图取景", "视线"),
    ("画面", "视角", "构图取景", "视角"),
    # R18 / 负面词
    ("内置分类-禁", "", "内置分类-禁", "R18"),
    ("内置分类-禁", "性行为", "内置分类-禁", "R18"),
    ("内置分类-禁", "胸", "内置分类-禁", "R18"),
    ("反向", "", "反向", "负面词"),
    ("反向", "负面提示", "反向", "负面词"),
    # ---- 第二轮合并：按「穿在哪 / 长在哪」重排，少而正交 ----
    ("人物", "发型", "人物", "头发"),
    ("人物", "发色", "人物", "头发"),
    ("人物", "五官", "人物", "面部"),
    ("人物", "表情", "人物", "面部"),
    ("人物", "体形与肤色", "人物", "体貌特征"),
    ("人物", "职业", "人物", "身份"),
    ("背景", "户外", "背景", "场景"),
    ("背景", "室内", "背景", "场景"),
    ("元标签", "翻译", "元标签", "图注"),
    ("构图取景", "特写", "构图取景", "镜头"),
    ("构图取景", "视线", "构图取景", "视角"),
    ("画面", "氛围", "背景", "氛围"),
]
MERGE_MAP = {(a, b): (c, d) for a, b, c, d in MERGE}

# 页面分类按钮的优先序（越靠前越优先；没列到的按条数排在后面）
L1_ORDER = ["人物", "构图取景", "背景", "画面", "物件", "元标签", "反向", "内置分类-禁",
            "kontext指令", "角色", "画师", "作品"]

# ---------------------------------------------------------------- 人工覆盖表
# 规则认不出、但一眼就能定的词，直接在这里点名（按标签名，优先于关键词规则）。
# 可以一批一批加：跑完 classify_tags.py 看 reports/unmatched_*.txt，把新的一批贴进来即可。
OVERRIDES = {
    "...": ("人物", "表情"),
    "tearing_up": ("人物", "服装"),
    "faceless": ("人物", "体貌特征"),
    "motor_vehicle": ("物件", ""),
    "forehead": ("人物", "五官"),
    "androgynous": ("人物", "体形与肤色"),
    "facial": ("内置分类-禁", "R18"),
    "restrained": ("人物", "姿势动作"),
    "spikes": ("人物", "发型"),
    "clothing_aside": ("内置分类-禁", "R18"),
    "side_slit": ("人物", "服装"),
    "floating": ("人物", "姿势动作"),
    "science_fiction": ("元标签", "图注"),
    "licking": ("人物", "姿势动作"),
    "veins": ("人物", "体貌特征"),
    "spot_color": ("画面", "装饰"),
    "knee_up": ("人物", "姿势动作"),
    "desk": ("物件", ""),
    "front-tie_top": ("人物", "服装"),
    "dual_persona": ("元标签", "图注"),
    "gift": ("物件", ""),
    "beads": ("人物", "配饰"),
    "convenient_censoring": ("内置分类-禁", "R18"),
    ":<": ("人物", "表情"),
    "toned": ("人物", "体形与肤色"),
    "furrowed_brow": ("人物", "表情"),
    "!": ("人物", "表情"),
    "reflection": ("画面", "装饰"),
    "handgun": ("物件", ""),
    "wading": ("人物", "姿势动作"),
    "seiza": ("人物", "姿势动作"),
    "tray": ("物件", ""),
    "alcohol": ("物件", ""),
    "kemonomimi_mode": ("人物", "物种"),
    "headset": ("人物", "配饰"),
    "@_@": ("人物", "表情"),
    "pouch": ("物件", ""),
    "personification": ("元标签", "图注"),
    "spoken_ellipsis": ("人物", "表情"),
    "age_difference": ("人物", "体形与肤色"),
    "jitome": ("人物", "表情"),
    "partially_submerged": ("人物", "姿势动作"),
    "bulge": ("内置分类-禁", "R18"),
    "one-hour_drawing_challenge": ("元标签", "图注"),
    "wide-eyed": ("人物", "表情"),
    "emphasis_lines": ("画面", "装饰"),
    "thong": ("人物", "服装"),
    "epaulettes": ("人物", "服装"),
    "fingering": ("内置分类-禁", "R18"),
    "flying": ("人物", "姿势动作"),
    "cleft_of_venus": ("内置分类-禁", "R18"),
    "head_rest": ("人物", "姿势动作"),
    "notice_lines": ("画面", "装饰"),
    ":q": ("人物", "表情"),
    "broom": ("物件", ""),
    "straight-on": ("构图取景", "视角"),
    "height_difference": ("人物", "体形与肤色"),
    "dual_wielding": ("人物", "姿势动作"),
    "sideburns": ("人物", "发型"),
    "threesome": ("人物", "对象与数量"),
    "blurry_foreground": ("画面", "装饰"),
    "2koma": ("元标签", "媒介"),
    "innertube": ("物件", ""),
    "contrapposto": ("人物", "姿势动作"),
    "circlet": ("人物", "配饰"),
    "+_+": ("人物", "表情"),
    "oni": ("人物", "物种"),
    "sideways_glance": ("构图取景", "视线"),
    "bouquet": ("物件", ""),
    "breastplate": ("人物", "服装"),
    "naughty_face": ("人物", "表情"),
    "lollipop": ("物件", ""),
    "injury": ("人物", "体貌特征"),
    "eyeliner": ("人物", "配饰"),
    "brother_and_sister": ("人物", "身份"),
    "rock": ("背景", "场景"),
    "enmaided": ("人物", "服装"),
    "machinery": ("物件", ""),
    "toenail_polish": ("人物", "配饰"),
    "blunt_ends": ("人物", "发型"),
    "snowing": ("背景", "氛围"),
    "ice": ("物件", ""),
    "sheathed": ("物件", ""),
    ":t": ("人物", "表情"),
    "forehead_mark": ("人物", "五官"),
    "stairs": ("背景", "场景"),
    "leash": ("内置分类-禁", "R18"),
    "sound_effects": ("画面", "装饰"),
    "=_=": ("人物", "表情"),
    "popsicle": ("物件", ""),
    "sarashi": ("人物", "服装"),
    "!?": ("人物", "表情"),
    "double-breasted": ("人物", "服装"),
    "upside-down": ("构图取景", "视角"),
    "shrug_(clothing)": ("人物", "服装"),
    "tiles": ("背景", "场景"),
    "chromatic_aberration": ("画面", "装饰"),
    "minigirl": ("人物", "体形与肤色"),
    "strawberry": ("物件", ""),
    "borrowed_character": ("元标签", "图注"),
    # 第二批（继续按热度往下扫）
    "drawstring": ("人物", "服装"),
    "abyssal_ship": ("人物", "物种"),
    "motion_blur": ("画面", "装饰"),
    "music": ("画面", "氛围"),
    "railing": ("背景", "场景"),
    ";)": ("人物", "表情"),
    "contemporary": ("元标签", "图注"),
    "interracial": ("人物", "身份"),
    "alternate_color": ("元标签", "图注"),
    "bespectacled": ("人物", "配饰"),
    "branch": ("背景", "场景"),
    "smoking": ("人物", "姿势动作"),
    "oekaki": ("元标签", "媒介"),
    "tabard": ("人物", "服装"),
    "ofuda": ("物件", ""),
    "fence": ("背景", "场景"),
    "zoom_layer": ("构图取景", "构图"),
    "page_number": ("元标签", "图注"),
    "smug": ("人物", "表情"),
    "vision_(genshin_impact)": ("人物", "配饰"),
    "kneepits": ("人物", "体貌特征"),
    "apple": ("物件", ""),
    "bloomers": ("人物", "服装"),
    "tachi-e": ("元标签", "媒介"),
    "blindfold": ("人物", "配饰"),
    "size_difference": ("人物", "体形与肤色"),
    "gag": ("内置分类-禁", "R18"),
    "armpit_crease": ("人物", "体貌特征"),
    "anklet": ("人物", "配饰"),
    "sunflower": ("物件", ""),
    "|_|": ("人物", "表情"),
    "underbust": ("人物", "服装"),
    "center_opening": ("人物", "服装"),
    "pen": ("物件", ""),
    "wand": ("物件", ""),
    "spoken_question_mark": ("人物", "表情"),
    "headpiece": ("人物", "配饰"),
    "bishounen": ("人物", "身份"),
    "folding_fan": ("物件", ""),
    "bandeau": ("人物", "服装"),
    "gakuran": ("人物", "服装"),
    "lapels": ("人物", "服装"),
    "bookshelf": ("物件", ""),
    "ahegao": ("内置分类-禁", "R18"),
    "wristwatch": ("人物", "配饰"),
    "aircraft": ("物件", ""),
    "microskirt": ("人物", "服装"),
    "two-sided_fabric": ("人物", "服装"),
    "cable": ("物件", ""),
    "name_tag": ("元标签", "图注"),
    # 第三批
    "on_head": ("人物", "配饰"),
    "bush": ("背景", "场景"),
    "electricity": ("画面", "装饰"),
    "inkling": ("人物", "物种"),
    "joints": ("人物", "体貌特征"),
    "shared_bathing": ("人物", "姿势动作"),
    "w": ("人物", "表情"),
    "pom_pom_(cheerleading)": ("人物", "配饰"),
    "crotch_seam": ("人物", "服装"),
    "controller": ("物件", ""),
    "limited_palette": ("画面", "艺术风格"),
    "vambraces": ("人物", "服装"),
    "reading": ("人物", "姿势动作"),
    "magic": ("画面", "装饰"),
    "chinese_zodiac": ("元标签", "图注"),
    "unbuttoned": ("人物", "服装"),
    "haori": ("人物", "服装"),
    "talking": ("人物", "姿势动作"),
    "forehead_jewel": ("人物", "配饰"),
    "riding": ("人物", "姿势动作"),
    "cannon": ("物件", ""),
    "pocky": ("物件", ""),
    "battle": ("元标签", "图注"),
    "partially_unbuttoned": ("人物", "服装"),
    "laughing": ("人物", "表情"),
    "fantasy": ("元标签", "图注"),
    "hitodama": ("画面", "装饰"),
    "dancing": ("人物", "姿势动作"),
    "gohei": ("物件", ""),
    "bald": ("人物", "发型"),
    # 第四批
    "bucket": ("物件", ""),
    "film_grain": ("画面", "装饰"),
    "dark": ("画面", "光照"),
    "interspecies": ("人物", "物种"),
    "bracer": ("人物", "配饰"),
    "company_name": ("元标签", "图注"),
    "wince": ("人物", "表情"),
    "randoseru": ("人物", "配饰"),
    "imminent_penetration": ("内置分类-禁", "R18"),
    "pointless_censoring": ("内置分类-禁", "R18"),
    "bathing": ("人物", "姿势动作"),
    "partially_colored": ("元标签", "媒介"),
    "carrot": ("物件", ""),
    "leather": ("人物", "服装"),
    "used_condom": ("内置分类-禁", "R18"),
    "scabbard": ("物件", ""),
    "watercraft": ("物件", ""),
    "halftone": ("元标签", "媒介"),
    "condom_wrapper": ("内置分类-禁", "R18"),
    "frog": ("人物", "物种"),
    "sexually_suggestive": ("内置分类-禁", "R18"),
    "gameplay_mechanics": ("元标签", "图注"),
    "public_indecency": ("内置分类-禁", "R18"),
    "rigging": ("元标签", "图注"),
    "anniversary": ("元标签", "图注"),
    "aura": ("画面", "装饰"),
    "stitches": ("人物", "体貌特征"),
    "anchor": ("物件", ""),
    "sack": ("物件", ""),
    "giant": ("人物", "体形与肤色"),
    "wagashi": ("物件", ""),
    "pumpkin": ("物件", ""),
    "old": ("人物", "体形与肤色"),
    "vines": ("背景", "场景"),
    "animalization": ("人物", "物种"),
    "shimenawa": ("物件", ""),
    "afterimage": ("画面", "装饰"),
    "in_container": ("构图取景", "构图"),
    "diamond_(shape)": ("画面", "装饰"),
    "winter": ("背景", "氛围"),
    "bath": ("背景", "场景"),
    "cowbell": ("人物", "配饰"),
    "singing": ("人物", "姿势动作"),
    "house": ("背景", "场景"),
    "coin": ("物件", ""),
    "onee-shota": ("人物", "身份"),
    "charm_(object)": ("物件", ""),
    "multiple_persona": ("元标签", "图注"),
    "biting": ("人物", "姿势动作"),
    "anime_coloring": ("元标签", "媒介"),
    "kicking": ("人物", "姿势动作"),
    "transparent": ("画面", "装饰"),
    "magatama": ("人物", "配饰"),
    "falling": ("人物", "姿势动作"),
    "tate_eboshi": ("人物", "配饰"),
    "mushroom": ("物件", ""),
    "peach": ("物件", ""),
    "x-ray": ("元标签", "图注"),
    "game_controller": ("物件", ""),
    "handheld_game_console": ("物件", ""),
    "folded": ("人物", "服装"),
    "summer": ("背景", "氛围"),
    "bonnet": ("人物", "配饰"),
    "stool": ("物件", ""),
    "birthday": ("元标签", "图注"),
    "cookie": ("物件", ""),
    "ribs": ("人物", "体貌特征"),
    "moaning": ("人物", "表情"),
    "peeing": ("内置分类-禁", "R18"),
    "ripples": ("画面", "装饰"),
    "side-by-side": ("构图取景", "构图"),
    "aiming": ("人物", "姿势动作"),
    "earphones": ("人物", "配饰"),
    "burger": ("物件", ""),
    "bamboo": ("背景", "场景"),
    "gold": ("画面", "装饰"),
    "camouflage": ("人物", "服装"),
    "name_connection": ("元标签", "图注"),
    "heads_together": ("人物", "姿势动作"),
    "magic_circle": ("画面", "装饰"),
    "double_penetration": ("内置分类-禁", "R18"),
    "voice_actor_connection": ("元标签", "图注"),
    "pee": ("内置分类-禁", "R18"),
    "syringe": ("物件", ""),
    "shell": ("物件", ""),
    "oversized_object": ("构图取景", "构图"),
    "cherry": ("物件", ""),
    "dirty": ("人物", "体貌特征"),
    "dripping": ("人物", "体貌特征"),
    "chalkboard": ("背景", "场景"),
    "fake_screenshot": ("元标签", "媒介"),
    "trigger_discipline": ("人物", "姿势动作"),
    "splashing": ("画面", "装饰"),
    "notched_lapels": ("人物", "服装"),
    "saucer": ("物件", ""),
    "bathtub": ("背景", "场景"),
    "rice": ("物件", ""),
    "sheet_grab": ("人物", "姿势动作"),
    "lanyard": ("人物", "配饰"),
    "watermelon": ("物件", ""),
    "trait_connection": ("元标签", "图注"),
    "motorcycle": ("物件", ""),
    "manly": ("人物", "体形与肤色"),
    "sandwiched": ("人物", "对象与数量"),
    "skeleton": ("人物", "体貌特征"),
    "floating_object": ("画面", "装饰"),
    "whistle": ("物件", ""),
    "egg": ("物件", ""),
    "scroll": ("物件", ""),
    "mind_control": ("元标签", "图注"),
    # 第五批
    "gap_(touhou)": ("人物", "身份"),
    "object_on_head": ("人物", "配饰"),
    "feeding": ("人物", "姿势动作"),
    "clipboard": ("物件", ""),
    "cooking": ("人物", "姿势动作"),
    "futon": ("物件", ""),
    "race_queen": ("人物", "身份"),
    "jaggy_lines": ("画面", "装饰"),
    "tape": ("物件", ""),
    "merry_christmas": ("元标签", "图注"),
    "sakazuki": ("物件", ""),
    "bruise": ("人物", "体貌特征"),
    "content_rating": ("元标签", "图注"),
    "tank": ("物件", ""),
    "pillar": ("背景", "场景"),
    "prosthesis": ("人物", "体貌特征"),
    "humanization": ("人物", "物种"),
    "recording": ("人物", "姿势动作"),
    "giantess": ("人物", "体形与肤色"),
    "ranguage": ("元标签", "图注"),
    "torpedo": ("物件", ""),
    "planted": ("背景", "场景"),
    "earclip": ("人物", "配饰"),
    "hachimaki": ("人物", "配饰"),
    "utility_pole": ("背景", "场景"),
    "dougi": ("人物", "服装"),
    "nightgown": ("人物", "服装"),
    "kariginu": ("人物", "服装"),
    "crack": ("画面", "装饰"),
    "evening": ("背景", "氛围"),
    "punching": ("人物", "姿势动作"),
    "octoling": ("人物", "物种"),
    "meat": ("物件", ""),
    "partially_unzipped": ("人物", "服装"),
    "internal_cumshot": ("内置分类-禁", "R18"),
    "bride": ("人物", "身份"),
    "husband_and_wife": ("人物", "身份"),
    "sepia": ("画面", "装饰"),
    "playing_games": ("人物", "姿势动作"),
    "broken": ("物件", ""),
    "explosive": ("物件", ""),
    "company_connection": ("元标签", "图注"),
    "oripathy_lesion_(arknights)": ("人物", "体貌特征"),
    "dango": ("物件", ""),
    "taking_picture": ("人物", "姿势动作"),
    "pinky_out": ("人物", "姿势动作"),
    "uterus": ("人物", "体貌特征"),
    "twisted_torso": ("人物", "姿势动作"),
    "exhibitionism": ("内置分类-禁", "R18"),
    "firing": ("人物", "姿势动作"),
    "waves": ("背景", "氛围"),
    "take_your_pick": ("元标签", "图注"),
    "pervert": ("元标签", "图注"),
    "yukkuri_shiteitte_ne": ("元标签", "图注"),
    "pun": ("元标签", "图注"),
    "elbow_rest": ("人物", "姿势动作"),
    "whip": ("内置分类-禁", "R18"),
    "chess_piece": ("物件", ""),
    "median_furrow": ("人物", "体貌特征"),
    "onigiri": ("物件", ""),
    "bone": ("人物", "体貌特征"),
    "penguin": ("人物", "物种"),
    "amputee": ("人物", "体貌特征"),
    "barcode": ("元标签", "图注"),
    "kotatsu": ("背景", "场景"),
    "autumn": ("背景", "氛围"),
    "midair": ("构图取景", "构图"),
    "time_paradox": ("元标签", "图注"),
    "netorare": ("内置分类-禁", "R18"),
    "albino": ("人物", "体形与肤色"),
    "crotchless": ("内置分类-禁", "R18"),
    "suggestive_fluid": ("内置分类-禁", "R18"),
    "grapes": ("物件", ""),
    "hot": ("人物", "体貌特征"),
    "energy": ("画面", "装饰"),
    "yandere": ("人物", "身份"),
    "scene_reference": ("元标签", "图注"),
    "waking_up": ("人物", "姿势动作"),
    "cowlick": ("人物", "发型"),
    "lightning": ("画面", "装饰"),
    "money": ("物件", ""),
    "karakasa_obake": ("人物", "物种"),
    "bicycle": ("物件", ""),
    "ambiguous_gender": ("人物", "体形与肤色"),
    "nintendo_switch": ("物件", ""),
    "pole": ("物件", ""),
    "damaged": ("画面", "装饰"),
    "thank_you": ("元标签", "图注"),
    "fashion": ("人物", "服装"),
    "hypnosis": ("元标签", "图注"),
    "elbow_pads": ("人物", "配饰"),
    "clone": ("人物", "对象与数量"),
    "statue": ("物件", ""),
    "crow": ("人物", "物种"),
    "locker": ("背景", "场景"),
    "muted_color": ("画面", "装饰"),
    "spring_onion": ("物件", ""),
    "reference_inset": ("元标签", "图注"),
    "hairy": ("人物", "体貌特征"),
    "ladle": ("物件", ""),
    "turning_head": ("人物", "姿势动作"),
    "throne": ("物件", ""),
    "horror_(theme)": ("元标签", "图注"),
    "stick": ("物件", ""),
    "furry_with_non-furry": ("人物", "物种"),
    "reverse_trap": ("人物", "身份"),
    "lifting_person": ("人物", "姿势动作"),
    "quiver": ("物件", ""),
    "painting_(object)": ("物件", ""),
    "pouring": ("人物", "姿势动作"),
    "defeat": ("元标签", "图注"),
    "gears": ("物件", ""),
    "earpiece": ("人物", "配饰"),
    "partially_undressed": ("人物", "服装"),
    "coattails": ("人物", "服装"),
    "thorns": ("背景", "场景"),
    "crab": ("人物", "物种"),
    "reverse_grip": ("人物", "姿势动作"),
    "crotch": ("人物", "体貌特征"),
    "stand_(jojo)": ("人物", "物种"),
    # 第六批
    "raccoon_girl": ("人物", "物种"),
    "improvised_gag": ("内置分类-禁", "R18"),
    "tower": ("背景", "场景"),
    "poking": ("人物", "姿势动作"),
    "imagining": ("人物", "表情"),
    "hairpods": ("人物", "配饰"),
    "deep_penetration": ("内置分类-禁", "R18"),
    "lock": ("物件", ""),
    "shop": ("背景", "场景"),
    "hose": ("物件", ""),
    "reverse_bunnysuit": ("人物", "服装"),
    "puddle": ("背景", "场景"),
    "death": ("元标签", "图注"),
    "silk": ("人物", "服装"),
    "trident": ("物件", ""),
    "pillarboxed": ("画面", "装饰"),
    "toilet": ("背景", "场景"),
    "gourd": ("物件", ""),
    "danmaku": ("画面", "装饰"),
    "colorful": ("画面", "艺术风格"),
    "flaccid": ("人物", "体貌特征"),
    "circle": ("画面", "装饰"),
    "fighting": ("人物", "姿势动作"),
    "clover": ("物件", ""),
    "bullet": ("物件", ""),
    "lemon": ("物件", ""),
    "transformation": ("元标签", "图注"),
    "taur": ("人物", "物种"),
    "mandarin_orange": ("物件", ""),
    "assault_visor": ("人物", "配饰"),
    "tomato": ("物件", ""),
    "command_spell": ("画面", "装饰"),
    "flexible": ("人物", "体形与肤色"),
    "pawpads": ("人物", "体貌特征"),
    "too_many": ("人物", "对象与数量"),
    "miniboy": ("人物", "体形与肤色"),
    "after_fellatio": ("内置分类-禁", "R18"),
    "bodypaint": ("人物", "体貌特征"),
    "milk": ("物件", ""),
    "bite_mark": ("人物", "体貌特征"),
    "2022": ("元标签", "图注"),
    "spacesuit": ("人物", "服装"),
    "pizza": ("物件", ""),
    "kyuubi": ("人物", "物种"),
    "paint_splatter": ("画面", "装饰"),
    "thinking": ("人物", "表情"),
    "bolt_action": ("物件", ""),
    "fishing_rod": ("物件", ""),
    "brand_name_imitation": ("元标签", "图注"),
    "people": ("人物", "对象与数量"),
    "deepthroat": ("内置分类-禁", "R18"),
    "duck": ("人物", "物种"),
    "rubber_duck": ("物件", ""),
    "scope": ("物件", ""),
    "debris": ("画面", "装饰"),
    "unsheathed": ("物件", ""),
    "cage": ("物件", ""),
    "octopus": ("人物", "物种"),
    "chewing_gum": ("物件", ""),
    "spacecraft": ("物件", ""),
    "shide": ("物件", ""),
    "bleeding": ("人物", "体貌特征"),
    "sandwich": ("物件", ""),
    "parfait": ("物件", ""),
    "tsundere": ("人物", "身份"),
    "subtitled": ("元标签", "图注"),
    "assisted_exposure": ("内置分类-禁", "R18"),
    "glowstick": ("物件", ""),
    "novelty_censor": ("内置分类-禁", "R18"),
    "super_saiyan": ("人物", "物种"),
    "remote_control": ("物件", ""),
    "milestone_celebration": ("元标签", "图注"),
    "sushi": ("物件", ""),
    "throwing": ("人物", "姿势动作"),
    "showering": ("人物", "姿势动作"),
    "jirai_kei": ("人物", "服装"),
    "plunging_neckline": ("人物", "服装"),
    "talons": ("人物", "体貌特征"),
    "cheese": ("物件", ""),
    "au_ra": ("人物", "物种"),
    "song_name": ("元标签", "图注"),
    "banana": ("物件", ""),
    "pancake": ("物件", ""),
    "wiffle_gag": ("内置分类-禁", "R18"),
    "chicken": ("人物", "物种"),
    "cuts": ("人物", "体貌特征"),
    "rooftop": ("背景", "场景"),
    "gaping": ("内置分类-禁", "R18"),
    "color_guide": ("元标签", "图注"),
    "briefcase": ("物件", ""),
    "guro": ("内置分类-禁", "R18"),
    "map": ("物件", ""),
    "2021": ("元标签", "图注"),
    "game_console": ("物件", ""),
    "spitroast": ("内置分类-禁", "R18"),
    "evolutionary_line": ("元标签", "图注"),
    "glitch": ("画面", "装饰"),
    "diffraction_spikes": ("画面", "装饰"),
    "cream": ("物件", ""),
    "lipstick_mark": ("人物", "体貌特征"),
    "mitsudomoe_(shape)": ("画面", "装饰"),
    "lily_pad": ("背景", "场景"),
    "u_u": ("人物", "表情"),
    "frying_pan": ("物件", ""),
    "megaphone": ("物件", ""),
    "mochi": ("物件", ""),
    "embers": ("画面", "装饰"),
    "hagoromo": ("人物", "服装"),
    "string_of_fate": ("元标签", "图注"),
    "kanzashi": ("人物", "配饰"),
    "lineup": ("人物", "对象与数量"),
    "spade_(shape)": ("画面", "装饰"),
    "corruption": ("元标签", "图注"),
    "alternate_form": ("元标签", "图注"),
    "needle": ("物件", ""),
    "numbered": ("元标签", "图注"),
    "lifebuoy": ("物件", ""),
    "twitching": ("人物", "姿势动作"),
    "french_fries": ("物件", ""),
    "instant_loss": ("内置分类-禁", "R18"),
    "writing": ("人物", "姿势动作"),
    "figure": ("物件", ""),
    "hiding": ("人物", "姿势动作"),
    "left-handed": ("元标签", "图注"),
    "driving": ("人物", "姿势动作"),
    "uchiwa": ("物件", ""),
    "cosmetics": ("人物", "配饰"),
    "shovel": ("物件", ""),
    "puppet": ("物件", ""),
    "pill": ("物件", ""),
    # 第七批：前 5000 的最后一批
    "grinding": ("人物", "姿势动作"),
    "chinese_knot": ("物件", ""),
    "spanked": ("内置分类-禁", "R18"),
    "treble_clef": ("画面", "装饰"),
    "medal": ("人物", "配饰"),
    "shikishi": ("物件", ""),
    "slave": ("人物", "身份"),
    "spill": ("画面", "装饰"),
    "object_namesake": ("元标签", "图注"),
    "earbuds": ("人物", "配饰"),
    "nightcap": ("人物", "配饰"),
    "head-mounted_display": ("人物", "配饰"),
    "pudding": ("物件", ""),
    "electric_fan": ("物件", ""),
    "jellyfish": ("人物", "物种"),
    "omelet": ("物件", ""),
    "praying": ("人物", "姿势动作"),
    "smell": ("人物", "表情"),
    "binoculars": ("物件", ""),
    "squirrel_girl": ("人物", "物种"),
    "stethoscope": ("物件", ""),
    "pinching": ("人物", "姿势动作"),
    "chainsaw": ("物件", ""),
    "strangling": ("内置分类-禁", "R18"),
    "reverse_upright_straddle": ("内置分类-禁", "R18"),
    "goldfish": ("人物", "物种"),
    "paint": ("元标签", "媒介"),
    "tokusatsu": ("元标签", "图注"),
    "laevatein_(touhou)": ("人物", "身份"),
    "peeing_self": ("内置分类-禁", "R18"),
    "screaming": ("人物", "表情"),
    "path": ("背景", "场景"),
    "come_hither": ("人物", "姿势动作"),
    "drumsticks": ("物件", ""),
    "light_trail": ("画面", "光照"),
    "seashell": ("物件", ""),
    "attack": ("人物", "姿势动作"),
    "cooperative_fellatio": ("内置分类-禁", "R18"),
    "onee-loli": ("人物", "身份"),
    "jealous": ("人物", "表情"),
    "sink": ("物件", ""),
    "scratches": ("人物", "体貌特征"),
    "submerged": ("背景", "场景"),
    "ladder": ("物件", ""),
    "carpet": ("背景", "场景"),
    "mating_press": ("内置分类-禁", "R18"),
    "duel": ("人物", "姿势动作"),
}

# ---------------------------------------------------------------- 关键词规则
HAIR_COLORS = ("blonde", "black", "brown", "blue", "red", "pink", "white", "grey", "gray", "green",
               "purple", "orange", "silver", "aqua", "multicolored", "two-tone", "gradient",
               "colored", "rainbow", "platinum", "ash", "chestnut", "auburn", "lavender", "mint",
               "teal", "turquoise", "violet", "magenta", "cyan", "gold", "golden")
R18 = ("nipple", "penis", "pussy", "sex", "cum", "anus", "vaginal", "pubic", "bdsm", "bondage",
       "areola", "clitoris", "testicles", "nude", "censored", "hetero", "yaoi", "yuri", "incest",
       "rape", "orgasm", "masturbation", "topless", "underboob", "sideboob", "no_bra",
       "no_panties", "pantyshot", "upskirt", "spread_legs", "presenting", "mosaic_censoring",
       "cameltoe")
META = ("translated", "translation_request", "check_translation", "artist_name", "character_name",
        "copyright_name", "signature", "speech_bubble", "english_text", "watermark", "bad_id",
        "dated", "commentary", "commentary_request", "japanese_text", "chinese_text", "korean_text",
        "artist_logo", "web_address", "twitter_username", "patreon_username", "logo", "text",
        "still_life", "third-party_edit", "bad_twitter_id", "bad_link", "large_filesize",
        "commission", "reference_sheet", "character_sheet", "multiple_views", "photo",
        "(medium)", "_media", "watercolor", "oil_painting", "pixel_art", "greyscale", "monochrome",
        "comic", "sketch", "lineart", "storyboard", "cover", "sample", "unfinished",
        "traditional", "vector", "tracing", "parody", "meme", "crossover", "spoiler", "animated",
        "high_contrast", "official_art", "fan_art", "ai-generated")
# 题材 / 生物 / 身份：新桶「人物·物种」「人物·身份」
SPECIES = ("animal", "animals", "bird", "cat", "dog", "fox", "wolf", "rabbit", "bunny", "mouse",
           "tiger", "lion", "bear", "dragon", "snake", "fish", "whale", "shark", "insect", "bug",
           "butterfly", "moth", "spider", "horse", "deer", "sheep", "cow", "pig", "monkey",
           "pokemon", "pokemon_(creature)", "digimon", "robot", "android", "mecha", "cyborg",
           "slime", "ghost", "zombie", "vampire", "angel", "demon", "devil", "elf", "orc", "goblin",
           "fairy", "mermaid", "centaur", "lamia", "harpy", "kitsune", "nekomata", "tanuki",
           "yokai", "youkai", "alien", "dinosaur", "kaiju", "monster", "creature")
IDENTITY = ("virtual_youtuber", "vtuber", "idol", "singer", "dancer", "princess", "prince",
            "nurse", "doctor", "teacher", "student", "office_lady", "waitress", "maid", "miko",
            "knight", "samurai", "ninja", "soldier", "military", "police", "pirate", "wizard",
            "witch", "priest", "nun", "cheerleader", "swimmer", "tennis_player", "fighter",
            "otoko_no_ko", "futanari", "crossdressing", "genderbend", "gender_bend", "femboy",
            "onee-san", "big_sister", "little_sister", "mother", "father", "family",
            "siblings", "sisters", "brothers", "twins", "couple", "friends", "lovers")
# 画风 / 题材风格
STYLE = ("bara", "realistic", "semi-realistic", "3d", "3d_style", "chibi", "retro", "vaporwave",
         "cyberpunk", "steampunk", "ukiyo-e", "art_nouveau", "impressionism", "minimalism",
         "surreal", "abstract", "manga_style", "anime_style", "cartoon", "flat_color")
# 年龄（归「人物·体形与肤色」）
AGE = ("aged_up", "aged_down", "child", "children", "toddler", "baby", "elderly", "old_woman",
       "old_man", "young", "teen", "teenager", "adult")
FRAME = ("full_body", "upper_body", "lower_body", "cowboy_shot", "portrait", "close-up",
         "wide_shot", "dutch_angle", "pov", "from_above", "from_below", "from_behind", "from_side",
         "facing_viewer", "facing_away", "looking_at_viewer", "looking_away", "looking_back",
         "looking_down", "looking_up", "head_out_of_frame", "cropped_torso", "cropped_legs",
         "feet_out_of_frame", "profile", "three_quarter_view", "back_view", "front_view",
         "side_view", "top-down_bottom-up", "horizon", "vanishing_point")
BG = ("outdoors", "indoors", "sky", "cloud", "night", "day", "sunset", "sunrise", "nature",
      "scenery", "water", "ocean", "sea", "river", "lake", "beach", "forest", "tree", "grass",
      "sand", "snow", "rain", "city", "building", "skyscraper", "street", "room", "wall", "floor",
      "ground", "ceiling", "window", "door", "curtain", "bed", "sofa", "plant", "petal", "leaf",
      "star_(sky)", "moon", "sun", "rainbow", "starry_sky", "night_sky", "blue_sky",
      "simple_background", "white_background", "grey_background", "black_background",
      "gradient_background", "checkered_background", "patterned_background", "no_humans",
      "architecture", "landscape", "cityscape", "classroom", "kitchen", "bathroom", "bedroom",
      "office", "cafe", "restaurant", "shrine", "temple", "church", "school", "train", "car",
      "airplane", "boat", "space", "galaxy", "nebula", "underwater", "cave", "field", "mountain",
      "desert", "island", "sunbeam", "light_rays", "lens_flare", "bokeh", "wind", "steam", "fog",
      "mist", "smoke")
CLOTH = ("shirt", "sleeve", "skirt", "dress", "pants", "shorts", "jeans", "sweater", "hoodie",
         "jacket", "coat", "apron", "uniform", "swimsuit", "bikini", "underwear", "panties", "bra",
         "lingerie", "leotard", "bodysuit", "swimwear", "kimono", "yukata", "robe", "scarf", "cape",
         "cloak", "vest", "suit", "necktie", "bowtie", "cardigan", "gown", "maid", "serafuku",
         "sailor_collar", "japanese_clothes", "chinese_clothes", "hijab", "turban", "crop_top",
         "strapless", "turtleneck", "ascot", "sash", "overalls", "camisole", "tank_top", "blouse",
         "poncho", "shawl", "mittens", "legwear", "open_clothes", "clothes", "wear", "costume",
         "cosplay", "outfit", "frill", "lace", "pleated", "striped_clothes", "plaid", "pocket",
         "button", "zipper", "collar", "neckerchief", "belt", "suspenders", "fur_trim", "fur_collar",
         "clothing_cutout", "clothes_removed", "undressing", "shirt_lift", "skirt_lift",
         "capelet", "sleeveless", "miniskirt", "maxiskirt", "playboy_bunny", "highleg",
         "zettai_ryouiki", "legwear", "sailor", "gym_uniform", "school_uniform", "halterneck",
         "hood_up", "hood_down", "military_uniform", "armor", "armour", "blazer", "denim", "obi",
         "animal_print", "polka_dot", "patterned", "sarong", "hakama", "harem_pants",
         "pencil_skirt", "pleated_skirt", "school_swimsuit", "thigh_boots")
ACC = ("glove", "sock", "stocking", "thighhigh", "kneehigh", "pantyhose", "boot", "shoe",
       "sandal", "sneaker", "loafer", "heel", "hat", "cap", "helmet", "beret", "crown", "tiara",
       "ribbon", "bow", "hairband", "headband", "headphones", "earmuffs", "earring", "necklace",
       "pendant", "bracelet", "bangle", "choker", "wrist_cuffs", "cuff", "glasses", "sunglasses",
       "goggles", "eyepatch", "mask", "watch", "ring", "hair_ornament", "hair_accessory",
       "hair_bow", "hair_flower", "hair_ribbon", "veil", "badge", "armband", "garter", "corset",
       "bandage", "bandaid", "plaster", "bell", "jewelry", "brooch", "hairpin", "hairclip",
       "barrette", "wristband", "leg_garter", "headgear", "scrunchie", "eyewear_on_head", "tassel",
       "hair_scrunchie", "glasses_on_head")
FACE = ("eye", "pupil", "iris", "eyelash", "eyebrow", "mouth", "lip", "teeth", "tongue", "fang",
        "stubble", "nose", "antlers", "beard", "moustache", "horn", "horns", "facial_mark")
EXPR = ("smile", "blush", "frown", "grin", "cry", "tear", "angry", "anger", "surpris",
        "embarrass", "sweat", "sweatdrop", "drool", "expression", "open_mouth", "closed_mouth",
        "parted_lips", "pout", "smirk", "laugh", "giggle", "scream", "yawn", "sleepy", "shy",
        "worried", "sad", "disgust", "confused", "scared", "nervous", "serious", "expressionless",
        "sigh", "kiss", ":d", ":(", "o_o", ":o", ":3", "^_^", ">_<", "uwu", ":>", ":-d", ";)",
        "xd", "happy", "trembling", "drooling", "?", ";d", "nosebleed")
BODY = ("breast", "cleavage", "navel", "thigh", "leg", "foot", "feet", "toes", "hand", "hands",
        "finger", "fingers", "arm", "arms", "ass", "butt", "hip", "hips", "waist", "collarbone",
        "neck", "shoulder", "back", "chest", "stomach", "belly", "midriff", "groin", "abs",
        "muscle", "muscular", "skin", "tail", "ear", "ears", "wing", "wings", "mole", "freckles",
        "tan", "tanlines", "pale", "wet", "blood", "scales", "fur", "whiskers", "claws", "paw",
        "tentacle", "fin", "gills", "antenna", "ahoge", "barefoot", "nails", "fingernails",
        "sole", "soles", "piercing", "saliva", "scar", "skindentation", "tattoo", "body_writing",
        "pectorals")
HAIR_WORDS = ("hair", "bangs", "ponytail", "twintail", "braid", "sidelock", "sidelocks", "bun",
              "bob_cut", "hime_cut", "drill", "curly", "wavy", "straight_hair", "spiky", "messy",
              "floating_hair", "wet_hair", "hair_intakes", "hair_between_eyes", "hair_over_shoulder",
              "hair_over_eye", "hair_up", "half_updo", "updo", "afro", "dreadlocks", "mohawk",
              "shaved", "short_hair", "long_hair", "medium_hair", "hair_ribbon", "hair_bow",
              "hairstyle", "hair_style", "alternate_hairstyle")
POSE = ("sitting", "standing", "lying", "kneel", "squat", "crouch", "walking", "running",
        "jumping", "holding", "crossed", "spread", "leaning", "stretching", "pose", "arms",
        "hands_on", "hand_up", "hand_on", "hand_out", "outstretched", "waving", "pointing",
        "salute", "peace_sign", "v_sign", "thumbs_up", "covering", "touching", "grabbing",
        "carrying", "hugging", "embracing", "hug", "bent_over", "on_back", "on_stomach",
        "on_side", "peeking", "walking_away", "head_tilt", "tilted_head", "arms_up",
        "arms_behind_back", "arms_crossed", "legs_crossed", "legs_together", "leg_lift",
        "hand_on_hip", "hand_on_chest", "hands_up", "yawning", "stretching_arms", "v",
        "walking_away", "facing_away", "groping", "eating", "sleeping", "bound", "wariza",
        "knees_up")
QTY = ("solo", "1girl", "1boy", "2girls", "2boys", "multiple_girls", "multiple_boys", "male",
       "female", "solo_focus", "male_focus", "female_focus", "crowd", "group", "duo")
ITEM = ("flower", "weapon", "sword", "katana", "gun", "pistol", "rifle", "knife", "dagger",
        "spear", "arrow", "shield", "bag", "backpack", "purse", "handbag", "suitcase", "food",
        "fruit", "vegetable", "drink", "tea", "coffee", "cake", "bread", "ice_cream", "bottle",
        "cup", "glass", "teacup", "mug", "plate", "bowl", "fork", "spoon", "chopsticks", "book",
        "notebook", "letter", "envelope", "cellphone", "phone", "smartphone", "camera", "computer",
        "keyboard", "mouse", "monitor", "instrument", "guitar", "piano", "violin", "microphone",
        "umbrella", "parasol", "balloon", "candy", "cigarette", "pipe", "hand_fan", "lantern",
        "candle", "pillow", "cushion", "blanket", "towel", "mirror", "clock", "key", "chain",
        "rope", "doll", "stuffed", "plush", "toy", "ball", "dice", "card", "poster", "wind_chime",
        "rose", "vase", "flower_pot", "box", "basket", "speaker", "television", "chair", "table",
        "couch", "fire", "gem", "cross", "staff", "polearm", "crystal", "spear")
DECOR = ("sparkle", "star_(symbol)", "heart", "skull", "feather", "petals", "cherry_blossom",
         "leaves", "garland", "banner", "flag", "confetti", "bubble", "bubbles", "border",
         "pattern", "frame", "ornament", "ornamental", "filigree", "floral", "sticker", "badge",
         "motion_lines", "letterboxed", "speed_lines", "impact_lines")
LIGHT = ("lighting", "backlighting", "glowing", "glow", "shadow", "shadows", "rim_light",
         "spotlight", "sunbeam", "light_rays", "lens_flare", "bokeh", "dramatic_lighting",
         "chiaroscuro", "god_rays", "bloom", "flare", "silhouette", "backlit", "sunlight",
         "light_particles", "sparkling", "glint", "sunbeam")
# 第二轮补词：按未认出清单的词频统计补出来的"家族"
CLOTH += ("jumpsuit", "pajamas", "buruma", "trim", "strap", "straps", "shoulder_strap", "tube_top",
          "hooded", "coat_dress", "long_coat", "fur_coat", "sportswear")
ACC += ("eyewear", "headwear", "halo", "bandana", "footwear", "eyeshadow", "tinted_glasses",
        "makeup", "ear_ornament", "nose_ring", "belly_chain", "waistband", "collar_chain",
        "fishnets", "sheath")
ITEM += ("chocolate", "gemstone", "paper", "note", "musical_note", "can", "sign", "signboard",
         "tube", "test_tube", "toy_car", "straw", "jar", "crescent")
FACE += ("cheek", "cheeks", "sclera", "toenails", "nails")
DECOR += ("outline", "emblem", "framed", "spoken_heart", "star_pattern", "heart_pattern",
          "floral_print", "checkered", "striped", "polka_dot", "^^^")
STYLE += ("slice_of_life", "game_style", "photo_style", "painting_style", "foreshortening")
BODY += ("body", "body_focus")
POSE += ("pulling", "pulling_clothes", "reaching", "reaching_out", "gripping")
# ---------------------------------------------------------------- 中文语义规则
# 英文词根认不出来时，看「中文译名」再判一次（前 20k 的中文是全的，这条命中率最高）。
# 一条中文词能覆盖一片，比英文词根划算；顺序＝优先级。
ZH_RULES = [
    ("内置分类-禁", "R18", ("性交", "性爱", "裸", "乳", "阴", "阴茎", "精液", "肛", "口交", "颜射", "自慰",
                            "乳头", "性器官", "勃起", "插入", "内射", "调教", "捆绑", "露出", "绝对领域",
                            "下体", "射精", "强奸", "性行为", "色情", "淫")),
    ("元标签", "翻译", ("翻译",)),
    ("元标签", "媒介", ("媒介", "上色手法", "画法", "像素", "黑白", "单色", "水墨", "油画", "素描", "线稿",
                        "描绘板", "立绘", "草图", "涂鸦", "2格漫画", "漫画风")),
    ("元标签", "图注", ("签名", "署名", "水印", "对话框", "页码", "挑战", "注释", "拟人", "梗", "恶搞",
                        "联动", "二创", "借用", "用户名", "现代", "时代", "科幻", "奇幻", "题材")),
    ("画面", "画质", ("分辨率", "画质", "高清", "超清", "模糊", "马赛克")),
    ("画面", "光照", ("光照", "光线", "逆光", "背光", "发光", "闪光", "阴影", "光斑", "镜头光晕", "阳光",
                      "灯光", "辉光", "反光", "倒影")),
    ("画面", "装饰", ("图案", "花纹", "装饰", "边框", "线条", "色差", "特效", "纹理", "符号", "标记")),
    ("画面", "艺术风格", ("风格", "画风", "流派", "派系", "印象", "抽象", "超现实", "赛博", "蒸汽波",
                          "复古", "极简", "卡通", "写实", "Q版", "赛璐璐", "哥特", "洛丽塔")),
    ("构图取景", "全身", ("全身",)),
    ("构图取景", "半身", ("半身", "上半身", "下半身")),
    ("构图取景", "特写", ("特写", "近景", "大特写")),
    ("构图取景", "镜头", ("镜头", "中景", "远景", "全景", "广角", "视点", "视角", "仰视", "俯视", "鸟瞰",
                          "俯角", "仰角", "远景")),
    ("构图取景", "视线", ("看向", "视线", "凝视", "瞟", "回眸", "目光")),
    ("构图取景", "构图", ("构图", "对称", "居中", "倒置", "颠倒", "身高差", "大小时差", "缩放")),
    ("背景", "纯色背景", ("纯色背景", "白背景", "黑背景", "灰背景", "透明背景", "简单背景", "渐变背景")),
    ("背景", "户外", ("室外", "户外", "野外")),
    ("背景", "室内", ("室内", "屋里", "房间内")),
    ("背景", "氛围", ("天空", "云", "星", "月", "太阳", "夕阳", "黄昏", "夜晚", "白天", "雪", "雨", "风",
                      "雾", "烟", "气氛", "氛围", "季节", "樱花", "花瓣", "自然", "风景", "山", "海", "湖",
                      "河", "森林", "树", "草地", "沙滩", "宇宙", "星空", "温泉", "竹林")),
    ("背景", "场景", ("房间", "卧室", "客厅", "厨房", "浴室", "教室", "学校", "办公室", "咖啡店", "餐厅",
                      "街道", "道路", "城市", "建筑", "墙", "地面", "地砖", "榻榻米", "楼梯", "栏杆", "围栏",
                      "窗", "门", "床", "沙发", "桌子", "椅子", "长凳", "书架", "家具", "桥", "车站", "电车",
                      "汽车", "飞机", "船", "机械", "废墟", "洞穴", "水面", "泳池", "桌")),
    ("人物", "物种", ("兽耳", "猫耳", "狐耳", "恶魔", "天使", "龙", "精灵", "机器人", "怪物", "宝可梦",
                      "猫娘", "狐娘", "兔娘", "吸血鬼", "僵尸", "鬼", "妖怪", "人鱼", "人马", "半兽人",
                      "动物", "鸟", "猫", "狗", "狼", "兔子", "马", "蝴蝶")),
    ("人物", "身份", ("偶像", "歌手", "舞者", "公主", "王子", "护士", "医生", "老师", "学生", "女仆", "巫女",
                      "骑士", "武士", "忍者", "士兵", "军人", "警察", "海盗", "魔法师", "女巫", "修女",
                      "拉拉队", "运动员", "虚拟主播", "男扮女装", "女装", "性转", "姐妹", "兄弟", "情侣",
                      "家人", "兄妹", "职业")),
    ("人物", "发型", ("发型", "头发", "刘海", "马尾", "辫", "发髻", "卷发", "直发", "短发", "长发", "蓬松",
                      "呆毛", "丸子头", "鬓角", "发梢")),
    ("人物", "发色", ("发色", "金发", "黑发", "白发", "红发", "蓝发", "棕发", "茶发", "粉发", "绿发", "紫发",
                      "银发", "灰发", "挑染", "渐变发", "彩色头发")),
    ("人物", "五官", ("眼睛", "眼", "瞳孔", "睫毛", "眉毛", "嘴", "唇", "牙", "舌", "鼻", "脸庞", "脸",
                      "额头", "腮", "颊", "雀斑", "痣", "面")),
    ("人物", "表情", ("表情", "笑容", "微笑", "哭", "泪", "怒", "生气", "惊讶", "害羞", "无语", "困",
                      "难过", "厌恶", "困惑", "害怕", "紧张", "认真", "面无表情", "眨眼", "吐舌",
                      "表情符号", "颜文字")),
    ("人物", "姿势动作", ("姿势", "站姿", "坐姿", "躺", "跪", "蹲", "走", "跑", "跳", "抱", "举", "挥手",
                          "指向", "敬礼", "比心", "交叉", "托腮", "托脸", "伸手", "抓", "拿", "抚摸",
                          "抱膝", "腾空", "漂浮", "飞行", "游泳", "蹚水", "回头", "侧身", "转身", "弯腰",
                          "手插兜", "手叉腰", "看书", "说话", "吃", "喝", "睡觉", "抽烟")),
    ("人物", "服装", ("衣服", "服装", "上衣", "衬衫", "袖子", "短袖", "长袖", "无袖", "裙", "裤", "牛仔裤",
                      "短裤", "外套", "夹克", "大衣", "风衣", "毛衣", "卫衣", "背心", "胸罩", "内衣", "泳衣",
                      "比基尼", "睡衣", "和服", "浴衣", "制服", "校服", "婚纱", "礼服", "斗篷", "围巾",
                      "领带", "领结", "腰带", "拉链", "纽扣", "开叉", "布料", "褶皱", "蕾丝", "印花",
                      "连体", "运动服", "汉服", "唐装", "旗袍", "露肩", "露背", "露脐", "紧身", "战袍")),
    ("人物", "配饰", ("饰品", "首饰", "耳环", "项链", "手链", "手镯", "戒指", "脚链", "发饰", "发带", "发夹",
                      "发绳", "头饰", "头环", "帽子", "头盔", "眼镜", "墨镜", "面具", "口罩", "手套", "护腕",
                      "手环", "手表", "腕表", "披肩", "胸针", "徽章", "蝴蝶结", "丝带", "缎带", "眼罩",
                      "束腰", "肩章", "靴", "鞋", "凉鞋", "高跟", "袜", "丝袜", "网袜", "长袜", "短袜",
                      "过膝袜", "吊带袜", "杖", "手杖")),
    ("人物", "体形与肤色", ("体型", "身材", "身高", "肤色", "皮肤", "肌肉", "健美", "丰满", "苗条", "胖",
                            "瘦", "矮", "高个", "年龄", "年轻", "年长", "婴儿", "小孩", "老人", "小麦色",
                            "结实")),
    ("人物", "体貌特征", ("身体", "部位", "胸", "乳房", "乳沟", "肚脐", "腹", "腰", "胯", "臀", "腿", "大腿",
                          "小腿", "膝", "脚", "足", "脚趾", "手", "手指", "指甲", "手臂", "肩", "背", "脖子",
                          "锁骨", "尾巴", "耳朵", "翅膀", "角", "血管", "伤痕", "纹身", "穿孔", "湿身",
                          "血迹", "汗", "肌", "萌袖", "膝盖窝")),
    ("人物", "对象与数量", ("单人", "一人", "两人", "多人", "三人", "群体", "无人物", "多女", "多男")),
    ("物件", "", ("物品", "物件", "武器", "剑", "刀", "枪", "弓", "盾", "矛", "斧", "锤", "魔杖", "书",
                  "笔记本", "笔", "纸", "信封", "花", "食物", "水果", "蔬菜", "饮料", "茶", "咖啡", "酒",
                  "蛋糕", "面包", "甜点", "冰棒", "糖果", "瓶", "杯", "碗", "盘", "餐具", "家具", "桌",
                  "椅", "沙发", "床", "灯", "镜子", "钟", "钥匙", "绳子", "链", "娃娃", "玩偶", "毛绒玩具",
                  "玩具", "球", "气球", "伞", "蜡烛", "宝石", "水晶", "宠物", "手机", "相机", "电脑",
                  "乐器", "吉他", "钢琴", "小提琴", "麦克风", "风扇", "扫帚", "托盘", "包裹", "礼物",
                  "牌子", "告示牌", "雪橇", "冰块", "稻草", "电缆", "机械", "飞机")),
]
# 第三轮：清单里剩下的常见词（一轮一轮加，收益递减就停）
CLOTH += ("casual", "buckle", "belt_buckle", "bridal_gauntlets", "gauntlets", "corset_piercing")
ACC += ("buckle", "collar_pin", "tie_clip")
EXPR += ("breath", "breathing", "panting", "gasp", "sighing", "whisper", "shouting")
IDENTITY += ("genderswap", "gender_swap", "tomboy", "gyaru", "cosplayer")
BODY += ("thick_thighs", "wide_hips", "body_part")
AGE += ("curvy", "plump", "slim", "tall", "short", "petite", "statuesque", "busty")
R18 += ("panty_pull", "clothes_pull", "downblouse", "wardrobe_malfunction")


def _tokens(name):
    return set(re.split(r"[_\-()\[\],. ]+", name.lower()))


def contains(name, words):
    """词表匹配：短词按「整词」命中（避免 car 命中 card、lace 命中 necklace），
    带下划线的词组或 7 字以上的长词才允许子串命中。"""
    n = name.lower()
    toks = _tokens(name)
    for w in words:
        if w in toks or (w + "s") in toks:
            return True
        if ("_" in w or len(w) >= 7) and w in n:
            return True
    return False


# ---------------------------------------------------------------- 服装/配饰 再细分
# 原本的「服装 / 配饰 / 汉服」是按来源分的，同一类东西（比如裙子和汉服裙子）会散在两边。
# 这里改成按**穿在哪**分：上身 / 下身 / 全身 / 鞋袜 / 头部饰品 / 脖子 / 耳朵 / 配饰。
# 命中顺序 = 优先级：先抓鞋袜/头/耳/颈，再抓明确的全身装，最后才是上/下身。
# 优先词（最高优先）：这些词里含别的词表的子串，必须先判，否则会归错
PRIOR_UPPER = ("连帽衫", "帽衫", "连帽卫衣", "兜帽", "hoodie", "hood", "cape", "capelet", "dress_shirt",
               "sailor_collar", "披风", "斗篷", "披肩")
L2_SHOES = ("boot", "shoe", "sandal", "sneaker", "loafer", "heel", "sock", "stocking", "thighhigh",
            "kneehigh", "pantyhose", "legwear", "garter", "鞋", "靴", "袜", "高跟", "凉鞋", "丝袜",
            "过膝袜", "长袜", "短袜", "网袜", "吊带袜", "拖鞋", "木屐")
L2_HEAD = ("hat", "cap", "helmet", "beret", "crown", "tiara", "hairband", "headband",
           "hair_ornament", "hair_accessory", "hair_bow", "hair_flower", "hair_ribbon", "headpiece",
           "headgear", "scrunchie", "veil", "hachimaki", "tate_eboshi", "bonnet", "nightcap",
           "circlet", "eyewear_on_head", "帽", "头盔", "发饰", "头饰", "头环", "头巾", "面纱",
           "发带", "发夹", "发绳", "发簪", "头戴", "王冠", "皇冠", "睡帽", "斗笠")
L2_EAR = ("earring", "ear_ornament", "earclip", "ear_piercing", "耳环", "耳饰", "耳夹", "耳钉", "耳挂")
L2_WAIST = ("belt", "sash", "waistband", "腰带", "腰封", "束腰", "皮带")
# 会被「按穿着部位重判」的二级（含旧桶）
CLOTH_L2 = ("服装", "配饰", "汉服", "上身装饰", "下身装饰", "全身装饰", "鞋袜", "头部饰品", "脖子", "耳朵")
# danbooru 的「概念 / meta」标签：说的不是具体穿在哪，归「其他」
L2_PERSON_META = ("alternate_costume", "official_alternate_costume", "cosplay", "undressing",
                  "clothes_removed", "no_clothes", "partially_undressed")
L2_NECK = ("choker", "necklace", "pendant", "collar_chain", "collar_pin", "tie_clip", "项链", "项圈",
           "锁骨链", "领针", "颈饰", "颈圈", "围脖")
L2_FULL = ("dress", "kimono", "yukata", "robe", "gown", "swimsuit", "bikini", "leotard", "bodysuit",
           "uniform", "sailor", "maid", "serafuku", "pajamas", "jumpsuit", "wedding",
           "chinese_clothes", "japanese_clothes", "dougi", "playboy_bunny", "hanfu", "overalls",
           "raincoat", "poncho", "连衣裙", "襦裙", "和服", "浴衣", "泳衣", "比基尼", "婚纱", "礼服",
           "旗袍", "汉服", "唐装", "制服", "校服", "道服", "战袍", "睡衣", "兔女郎", "女仆", "连体",
           "铠甲", "胸甲", "雨衣", "巫女服", "丧服", "圣诞装", "工装裤")
L2_LOWER = ("skirt", "pants", "shorts", "jeans", "bloomers", "hakama", "harem_pants", "裙", "裤",
            "百褶裙", "褶裙", "迷你裙", "内裤", "短裤", "牛仔裤", "灯笼裤", "围裙", "裙子")
L2_UPPER = ("shirt", "sweater", "hoodie", "jacket", "coat", "blazer", "cardigan", "vest", "tank_top",
            "camisole", "crop_top", "blouse", "t-shirt", "apron", "necktie", "bowtie", "scarf",
            "collar", "sleeve", "bra", "corset", "suspenders", "cape", "cloak", "shawl", "suit",
            "上衣", "衬衫", "衬衣", "毛衣", "卫衣", "背心", "外套", "夹克", "大衣", "风衣", "短袖",
            "长袖", "无袖", "胸罩", "内衣", "领带", "领结", "围巾", "袖子", "翻领", "开衫", "马甲",
            "抹胸", "胸衣", "斗篷", "披风", "披肩", "背带",
            # 汉服单品（按穿在哪归位，不再单独一个「汉服」桶）
            "上衫", "短衫", "长衫", "宋抹", "披帛", "霞帔", "领子")


def split_person_cloth(name, zh):
    """给 人物·服装 / 配饰 / 汉服 的行按「穿在哪」定二级；None = 没认出（调用方决定兜底）。"""
    hay = (name or "").lower() + " " + (zh or "")
    # 优先词：避免被其它词表截断误判（cape 不能命中 cap，连帽衫不能命中「帽」，
    # dress_shirt 不能命中 dress，belt_collar 要靠「脖子」但 belt 要归配饰）
    for k in PRIOR_UPPER:
        if k in hay:
            return "上身装饰"
    for l2, keys in (("鞋袜", L2_SHOES), ("头部饰品", L2_HEAD), ("耳朵", L2_EAR), ("脖子", L2_NECK),
                     ("配饰", L2_WAIST), ("全身装饰", L2_FULL), ("下身装饰", L2_LOWER),
                     ("上身装饰", L2_UPPER)):
        for k in keys:
            if k in hay:
                return l2
    return None


# ---------------------------------------------------------------- 物件 再细分
# 物件原本只有一个空二级（1239 条），挑出写提示词最常用的几类
ITEM_WEAPON = ("weapon", "sword", "dagger", "katana", "knife", "gun", "pistol", "rifle", "revolver",
               "shotgun", "cannon", "spear", "lance", "halberd", "polearm", "trident", "scythe",
               "whip", "mace", "grenade", "bomb", "missile", "shield", "quiver",
               "武器", "剑", "刀", "枪", "手术刀", "弓箭", "弓", "箭", "斧", "锤", "戟", "矛", "盾",
               "镰刀", "鞭", "炮弹", "手雷", "炸弹", "导弹")
ITEM_FOOD = ("food", "fruit", "vegetable", "bread", "toast", "cake", "candy", "sweets", "cookie",
             "chocolate", "drink", "juice", "tea", "coffee", "milk", "ice_cream", "dessert", "meat",
             "rice", "noodle", "sushi", "pizza", "burger", "donut", "macaron", "pancake",
             "食物", "水果", "蔬菜", "面包", "蛋糕", "糖果", "饼干", "巧克力", "饮料", "果汁", "茶",
             "咖啡", "牛奶", "冰淇淋", "甜点", "肉", "米饭", "面条", "寿司", "披萨", "甜甜圈")
ITEM_PLANT = ("flower", "petal", "rose", "leaf", "leaves", "tree", "branch", "grass", "plant",
              "bonsai", "vines", "seed", "mushroom", "cactus", "sunflower", "sakura", "cherry_blossom",
              "花", "玫瑰", "叶", "树", "草", "植物", "花瓣", "枝", "种子", "蘑菇", "仙人掌",
              "向日葵", "樱花", "盆栽")
ITEM_FURNITURE = ("chair", "table", "desk", "couch", "sofa", "bed", "pillow", "bench", "shelf",
                  "cabinet", "lamp", "mirror", "curtain", "carpet", "rug", "cushion", "stool",
                  "furniture", "dresser", "bookcase", "椅子", "桌", "沙发", "床", "枕头", "长椅",
                  "架子", "柜", "灯", "镜子", "窗帘", "地毯", "垫子", "床单")


def split_item(name, zh):
    """物件的二级：武器 / 食物 / 植物花卉 / 家具与家居；None = 归「其他物件」。"""
    hay = (name or "").lower() + " " + (zh or "")
    for l2, keys in (("武器", ITEM_WEAPON), ("食物", ITEM_FOOD), ("植物花卉", ITEM_PLANT),
                     ("家具与家居", ITEM_FURNITURE)):
        for k in keys:
            if k in hay:
                return l2
    return None


def classify(name, cat, zh=""):
    """返回 (一级, 二级)；None 表示这次不铺（画师 / 作品 / 角色名）。"""
    ov = OVERRIDES.get(name)          # 人工点名优先
    if ov:
        return ov
    n = name.lower()
    if cat in ("1", "3", "4"):                      # 垫底类：不铺，二级留空
        return None
    if contains(n, R18):
        return ("内置分类-禁", "R18")
    if contains(n, META):
        if "translat" in n:
            return ("元标签", "翻译")
        if ("(medium)" in n or "_media" in n or "watercolor" in n or "oil_painting" in n
                or "pixel_art" in n or "greyscale" in n or "monochrome" in n or "comic" in n
                or "sketch" in n or "lineart" in n):
            return ("元标签", "媒介")
        return ("元标签", "图注")
    if contains(n, ("highres", "absurdres", "lowres", "resolution", "quality", "8k", "4k")):
        return ("画面", "画质")
    if n.endswith(("_style", "_theme")):
        return ("画面", "艺术风格")
    if n.endswith(("_username", "_id")):
        return ("元标签", "图注")
    if n.endswith("_print"):
        return ("人物", "服装")
    if contains(n, LIGHT):
        return ("画面", "光照")
    if contains(n, STYLE):
        return ("画面", "艺术风格")
    if n.endswith("_background") or contains(n, BG):
        if n.endswith("_background"):
            return ("背景", "纯色背景")
        if "outdoors" in n:
            return ("背景", "户外")
        if "indoors" in n:
            return ("背景", "室内")
        if contains(n, ("room", "bedroom", "kitchen", "bathroom", "classroom", "office", "cafe",
                        "restaurant", "shrine", "temple", "church", "school", "street",
                        "architecture", "city", "building", "wall", "floor", "window", "door",
                        "bed", "sofa", "train", "car", "boat", "space")):
            return ("背景", "场景")
        return ("背景", "氛围")
    if contains(n, FRAME) or n.endswith("_focus") or n.startswith(("from_", "facing_", "looking_")):
        if n == "full_body":
            return ("构图取景", "全身")
        if n in ("upper_body", "lower_body"):
            return ("构图取景", "半身")
        if n == "cowboy_shot":
            return ("构图取景", "镜头")
        if n in ("portrait", "close-up", "wide_shot"):
            return ("构图取景", "特写")
        if n.startswith("looking_") or n == "facing_viewer":
            return ("构图取景", "视线")
        if n in ("dutch_angle", "pov", "from_above", "from_below", "profile", "back_view",
                 "front_view", "side_view", "three_quarter_view"):
            return ("构图取景", "视角")
        return ("构图取景", "构图")
    if contains(n, HAIR_WORDS):
        return ("人物", "发色") if (contains(n, HAIR_COLORS) and "hair" in n) else ("人物", "发型")
    if contains(n, SPECIES):
        return ("人物", "物种")
    if contains(n, IDENTITY):
        return ("人物", "身份")
    if contains(n, FACE):
        return ("人物", "五官")
    if contains(n, EXPR):
        return ("人物", "表情")
    if contains(n, BODY):
        return ("人物", "体貌特征")
    if contains(n, CLOTH):
        return ("人物", "服装")
    if contains(n, ACC):
        return ("人物", "配饰")
    if contains(n, AGE):
        return ("人物", "体形与肤色")
    if contains(n, POSE):
        return ("人物", "姿势动作")
    if contains(n, QTY):
        return ("人物", "对象与数量")
    if contains(n, DECOR) or n.endswith(("_pattern", "_frame", "_border")):
        return ("画面", "装饰")
    if contains(n, ITEM):
        return ("物件", "")
    # 英文词根没命中：拿中文译名再判一次（前 20k 的中文是齐的，这条命中率最高）
    z = (zh or "").strip()
    if z:
        for l1, l2, keys in ZH_RULES:
            for k in keys:
                if k in z:
                    return (l1, l2)
    if cat == "5":
        return ("元标签", "图注")
    return None


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    merge_only = "--merge-only" in args
    limit = 20000
    if "--limit-rank" in args:
        limit = int(args[args.index("--limit-rank") + 1])
    if not os.path.isfile(CSV):
        print("找不到 CSV:", CSV)
        return 1

    raw = open(CSV, "rb").read()
    had_bom = raw[:3] == b"\xef\xbb\xbf"
    text = raw.decode("utf-8-sig")
    eol = "\r\n" if "\r\n" in text else "\n"
    rows = list(csv.reader(io.StringIO(text)))

    heat = lambda r: int(r[2] or 0)
    order = sorted(range(len(rows)), key=lambda i: -heat(rows[i]))
    rank = {i: k + 1 for k, i in enumerate(order)}

    merged = filled = skipped = split_n = item_n = 0
    stat = collections.Counter()
    unmatched = []
    for i in range(len(rows)):
        r = rows[i]
        if len(r) != 8:
            continue
        l1, l2 = (r[5] or "").strip(), (r[6] or "").strip()
        if not l1 and l2 == "十八禁":          # 历史遗留：只有二级，补上一级
            r[5], r[6] = "内置分类-禁", "R18"
            merged += 1
            stat[("内置分类-禁", "R18")] += 1
            continue
        if l1:
            new = MERGE_MAP.get((l1, l2))
            if new and new != (l1, l2):
                r[5], r[6] = new
                merged += 1
            # 人物·服装 / 配饰 / 汉服 按「穿在哪」细分；已分过的桶也重判一次（改词表能自动纠错）
            cur = (r[6] or "").strip()
            if r[5] == "人物" and cur in CLOTH_L2:
                if r[0] in L2_PERSON_META and cur != "其他":
                    r[6] = "其他"
                    split_n += 1
                else:
                    sub = split_person_cloth(r[0], r[4] if len(r) > 4 else "")
                    if sub:
                        if sub != cur:
                            r[6] = sub
                            split_n += 1
                    elif cur == "服装":
                        r[6] = "上身装饰"
                        split_n += 1
                    elif cur == "汉服":
                        r[6] = "全身装饰"
                        split_n += 1
            # 历史遗留回补：早期把「耳朵」并进了「体貌特征」，耳饰这类要回到「耳朵」
            elif r[5] == "人物" and cur == "体貌特征":
                hay = (r[0] or "").lower() + " " + (r[4] if len(r) > 4 else "")
                if any(k in hay for k in L2_EAR):
                    r[6] = "耳朵"
                    split_n += 1
            # 物件：空二级 -> 武器 / 食物 / 植物花卉 / 家具与家居 / 其他物件
            elif r[5] == "物件":
                sub = split_item(r[0], r[4] if len(r) > 4 else "") or "其他物件"
                if cur != sub:
                    r[6] = sub
                    item_n += 1
            stat[(r[5], (r[6] or "").strip())] += 1
            continue
        if merge_only or rank[i] > limit:
            continue
        got = classify(r[0], r[1], r[4])
        if got is None:
            if r[1] in ("1", "3", "4"):
                skipped += 1
            else:
                unmatched.append(i)
            continue
        r[5], r[6] = got
        filled += 1
        stat[(got[0], got[1])] += 1

    print("二级合并（重写旧桶）:", merged, "行")
    print("服装/配饰按穿着部位细分:", split_n, "行")
    print("物件细分:", item_n, "行")
    print("规则分类（本次填补）:", filled, "行（热度前 %d 名）" % limit)
    print("垫底类（画师/角色/作品）跳过:", skipped, "行")
    print("规则没认出的:", len(unmatched), "行")
    print("")
    print("=== 分类分布（合并+填补后）===")
    by_l1 = collections.defaultdict(list)
    for (l1, l2), n in stat.items():
        by_l1[l1].append((l2 or "(空)", n))
    for l1 in sorted(by_l1, key=lambda x: (L1_ORDER.index(x) if x in L1_ORDER else 99)):
        items = sorted(by_l1[l1], key=lambda x: -x[1])
        print("%-12s %2d 个二级 / %5d 条：%s"
              % (l1, len(items), sum(n for _, n in items),
                 " | ".join("%s %d" % (a, b) for a, b in items[:20])))
    print("")
    print("=== 没认出的，按热度段 ===")
    bands = collections.Counter(0 if rank[i] <= 5000 else 1 if rank[i] <= 10000
                                else 2 if rank[i] <= 20000 else 3 for i in unmatched)
    for b, label in enumerate(("前5000", "5k-10k", "10k-20k", "20k 之后")):
        print("   %-9s %d" % (label, bands[b]))

    os.makedirs(REPORT_DIR, exist_ok=True)
    rep = os.path.join(REPORT_DIR, "classify_report.txt")
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("合并 %d 行 / 填补 %d 行 / 垫底类跳过 %d 行 / 未认出 %d 行（limit=%d, dry=%s）%s"
                 % (merged, filled, skipped, len(unmatched), limit, dry, os.linesep))
        for l1 in sorted(by_l1, key=lambda x: (L1_ORDER.index(x) if x in L1_ORDER else 99)):
            items = sorted(by_l1[l1], key=lambda x: -x[1])
            fh.write("%s: %s%s" % (l1, " | ".join("%s %d" % (a, b) for a, b in items), os.linesep))
    un = os.path.join(REPORT_DIR, "unmatched_%d.txt" % limit)
    with open(un, "w", encoding="utf-8") as fh:
        for i in sorted(unmatched, key=lambda x: rank[x]):
            fh.write("%6d\t%-9d\t%-32s\tcat=%s\tzh=%s%s"
                     % (rank[i], heat(rows[i]), rows[i][0], rows[i][1],
                        rows[i][4] or "-", os.linesep))
    print("")
    print("报告 ->", rep)
    print("未认出清单 ->", un)

    if dry:
        print("")
        print("[dry-run] 没有改任何文件")
        return 0

    if not os.path.exists(BACKUP):
        shutil.copy2(CSV, BACKUP)
        print("已备份 ->", os.path.basename(BACKUP))
    buf = io.StringIO()
    csv.writer(buf, lineterminator=eol).writerows(rows)
    data = buf.getvalue().encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    with open(CSV, "wb") as fh:
        fh.write(data)
    print("已写回:", CSV, "(%d 字节)" % len(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())



