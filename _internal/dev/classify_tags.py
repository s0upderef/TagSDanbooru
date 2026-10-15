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
    ("人物", "耳朵", "人物", "体貌特征"),
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
]
MERGE_MAP = {(a, b): (c, d) for a, b, c, d in MERGE}

# 页面分类按钮的优先序（越靠前越优先；没列到的按条数排在后面）
L1_ORDER = ["人物", "构图取景", "背景", "画面", "物件", "元标签", "反向", "内置分类-禁",
            "kontext指令", "角色", "画师", "作品"]

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


def classify(name, cat):
    """返回 (一级, 二级)；None 表示这次不铺（画师 / 作品 / 角色名）。"""
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

    merged = filled = skipped = 0
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
            stat[(r[5], (r[6] or "").strip())] += 1
            continue
        if merge_only or rank[i] > limit:
            continue
        got = classify(r[0], r[1])
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



