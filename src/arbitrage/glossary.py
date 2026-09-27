"""English -> Korean product vocabulary, so English supplier titles (Temu, AliExpress) can be
searched for and compared against Korean market listings.

No translation API: a bundled glossary of the words that appear in product titles (things,
materials, features, colours, brands), extendable with a CSV of your own (`english,korean`,
several Korean forms separated by `|`). Words the glossary doesn't know are dropped, so a
translation is a set of Korean key words, not a sentence. Matching stays strict: a translated
title alone never pairs two products (see matching.py); it needs a photo or a model code too.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from .errors import ConfigError

# english phrase -> Korean forms, most common first (the first one is used in search queries).
# Multi-word English keys are matched before single words.
_BUILTIN: dict[str, tuple[str, ...]] = {
    # kitchen
    "tongs": ("집게",), "kitchen tongs": ("주방집게", "집게"), "food tongs": ("집게",),
    "spatula": ("뒤집개", "스패츌러"), "turner": ("뒤집개",), "ladle": ("국자",), "whisk": ("거품기",),
    "peeler": ("필러", "감자칼"), "grater": ("강판",), "slicer": ("슬라이서", "채칼"), "chopper": ("다지기",),
    "cutting board": ("도마",), "chopping board": ("도마",), "knife": ("칼", "나이프"), "scissors": ("가위",),
    "kitchen scissors": ("주방가위",), "can opener": ("캔오프너", "병따개"), "bottle opener": ("병따개", "오프너"),
    "strainer": ("체", "거름망"), "colander": ("채반", "물빠짐"), "sieve": ("체",), "funnel": ("깔때기",),
    "measuring cup": ("계량컵",), "measuring spoon": ("계량스푼",), "mixing bowl": ("믹싱볼", "볼"),
    "bowl": ("볼", "그릇"), "plate": ("접시", "플레이트"), "dish": ("접시",), "cup": ("컵",), "mug": ("머그컵", "머그"),
    "tumbler": ("텀블러",), "bottle": ("병", "보틀"), "water bottle": ("물병", "워터보틀"), "thermos": ("보온병",),
    "kettle": ("전기포트", "케틀"), "electric kettle": ("전기포트",), "teapot": ("티팟", "찻주전자"),
    "pot": ("냄비",), "pan": ("팬", "프라이팬"), "frying pan": ("프라이팬",), "wok": ("웍",), "lid": ("뚜껑",),
    "steamer": ("찜기",), "rice cooker": ("밥솥",), "air fryer": ("에어프라이어",), "blender": ("믹서기", "블렌더"),
    "juicer": ("착즙기",), "toaster": ("토스터",), "coffee": ("커피",), "coffee maker": ("커피메이커",),
    "grinder": ("그라인더",), "coffee grinder": ("커피그라인더",), "dripper": ("드리퍼",), "french press": ("프렌치프레스",),
    "milk frother": ("우유거품기", "밀크프로더"), "spoon": ("스푼", "숟가락"), "fork": ("포크",), "chopsticks": ("젓가락",),
    "cutlery": ("커트러리",), "tableware": ("식기",), "lunch box": ("도시락", "런치박스"), "bento box": ("도시락",),
    "food container": ("밀폐용기", "반찬통"), "storage container": ("밀폐용기", "보관용기"), "container": ("용기",),
    "jar": ("병", "유리병"), "dispenser": ("디스펜서",), "soap dispenser": ("물비누디스펜서", "디스펜서"),
    "oil sprayer": ("오일스프레이",), "sprayer": ("스프레이", "분무기"), "spray bottle": ("분무기", "스프레이"),
    "rack": ("선반", "거치대", "랙"), "dish rack": ("식기건조대",), "drying rack": ("건조대",), "shelf": ("선반",),
    "organizer": ("정리함", "수납"), "storage": ("수납", "보관"), "storage box": ("수납박스", "수납함"),
    "basket": ("바구니",), "hook": ("후크", "고리"), "hanger": ("옷걸이",), "holder": ("홀더", "거치대"),
    "paper towel holder": ("키친타올걸이",), "trash can": ("쓰레기통",), "garbage bag": ("쓰레기봉투",),
    "sponge": ("스펀지", "수세미"), "scrubber": ("수세미",), "brush": ("브러시", "브러쉬"), "cleaning brush": ("청소브러시",),
    "apron": ("앞치마",), "oven mitt": ("오븐장갑",), "glove": ("장갑",), "gloves": ("장갑",), "mat": ("매트",),
    "silicone mat": ("실리콘매트",), "baking mat": ("베이킹매트",), "placemat": ("식탁매트",), "coaster": ("코스터", "컵받침"),
    "trivet": ("냄비받침",), "ice tray": ("얼음틀",), "ice cube tray": ("얼음틀",), "mold": ("몰드", "틀"), "mould": ("몰드",),
    "baking": ("베이킹",), "cake": ("케이크",), "egg": ("계란",), "egg separator": ("계란분리기",), "timer": ("타이머",),
    "kitchen scale": ("주방저울",), "scale": ("저울",), "thermometer": ("온도계",), "seal": ("실링", "밀봉"),
    "sealer": ("실링기",), "vacuum sealer": ("진공포장기",), "clip": ("클립",), "bag clip": ("봉지클립",),
    "faucet": ("수전",), "sink": ("싱크대",), "drain": ("배수구",), "filter": ("필터",),
    # home
    "pillow": ("베개", "쿠션"), "cushion": ("쿠션",), "blanket": ("담요", "블랭킷"), "bedding": ("침구",),
    "sheet": ("시트",), "curtain": ("커튼",), "rug": ("러그",), "carpet": ("카페트",), "doormat": ("현관매트",),
    "towel": ("타월", "수건"), "bath towel": ("목욕타월",), "bath mat": ("욕실매트",), "shower head": ("샤워헤드",),
    "shower": ("샤워",), "toothbrush": ("칫솔",), "toothbrush holder": ("칫솔걸이",), "soap": ("비누",),
    "toilet": ("변기", "화장실"), "toilet brush": ("변기솔",), "tissue": ("티슈",), "tissue box": ("티슈케이스",),
    "mirror": ("거울",), "lamp": ("램프", "조명"), "light": ("조명", "라이트"), "led light": ("LED조명", "LED등"),
    "night light": ("무드등", "수면등"), "desk lamp": ("책상조명", "스탠드"), "candle": ("캔들", "향초"),
    "diffuser": ("디퓨저",), "humidifier": ("가습기",), "dehumidifier": ("제습기",), "air purifier": ("공기청정기",),
    "fan": ("선풍기",), "heater": ("히터", "온풍기"), "clock": ("시계",), "wall clock": ("벽시계",), "alarm clock": ("알람시계",),
    "frame": ("프레임", "액자"), "photo frame": ("액자",), "vase": ("화병", "꽃병"), "plant": ("식물",), "flower pot": ("화분",),
    "planter": ("화분",), "artificial flower": ("조화",), "sticker": ("스티커",), "wallpaper": ("벽지",), "wall sticker": ("벽지스티커",),
    "door stopper": ("도어스토퍼", "문닫힘방지"), "door": ("문", "도어"), "lock": ("잠금", "락"), "padlock": ("자물쇠",),
    "drawer": ("서랍",), "closet": ("옷장",), "wardrobe": ("옷장",), "shoe rack": ("신발장", "신발정리대"),
    "umbrella": ("우산",), "laundry": ("세탁",), "laundry basket": ("빨래바구니",), "laundry bag": ("세탁망",),
    "lint remover": ("보풀제거기",), "iron": ("다리미",), "vacuum": ("청소기",),
    "vacuum cleaner": ("청소기",), "mop": ("물걸레", "밀대"), "broom": ("빗자루",), "duster": ("먼지털이",),
    "cleaner": ("클리너", "세정제"), "cleaning": ("청소",), "cloth": ("천", "행주"), "microfiber": ("극세사",),
    "desk": ("책상",), "chair": ("의자",), "table": ("테이블",), "stool": ("스툴",), "sofa": ("소파",), "bed": ("침대",),
    "mattress": ("매트리스",), "cover": ("커버",), "protector": ("보호",), "pad": ("패드",), "tray": ("트레이",),
    "tape": ("테이프",), "double sided tape": ("양면테이프",), "glue": ("접착제",), "rope": ("로프", "줄"),
    "string": ("끈",), "cable tie": ("케이블타이",), "zip tie": ("케이블타이",), "velcro": ("벨크로",), "magnet": ("자석",),
    "magnetic": ("자석", "마그네틱"), "screw": ("나사",), "tool": ("공구",), "tool set": ("공구세트",), "wrench": ("렌치",),
    "screwdriver": ("드라이버",), "hammer": ("망치",), "drill": ("드릴",), "tape measure": ("줄자",), "level": ("수평기",),
    "flashlight": ("손전등", "후레쉬"), "headlamp": ("헤드랜턴",), "lantern": ("랜턴",), "battery": ("배터리",),
    "rechargeable": ("충전식",), "solar": ("태양광",), "outdoor": ("아웃도어", "야외"), "camping": ("캠핑",),
    "tent": ("텐트",), "sleeping bag": ("침낭",), "cooler": ("쿨러", "아이스박스"),
    # electronics
    "phone": ("휴대폰", "폰", "스마트폰"), "smartphone": ("스마트폰",), "phone case": ("폰케이스", "휴대폰케이스"),
    "case": ("케이스",), "screen protector": ("액정보호필름", "강화유리"),
    "tempered glass": ("강화유리",), "phone holder": ("휴대폰거치대", "폰거치대"), "phone stand": ("휴대폰거치대", "스마트폰스탠드"),
    "car phone holder": ("차량용휴대폰거치대",), "car mount": ("차량용거치대",), "mount": ("거치대", "마운트"),
    "stand": ("스탠드", "거치대"), "tablet": ("태블릿",), "tablet stand": ("태블릿거치대",), "laptop": ("노트북",),
    "laptop stand": ("노트북거치대",), "laptop bag": ("노트북가방",), "keyboard": ("키보드",), "mouse": ("마우스",),
    "mouse pad": ("마우스패드",), "monitor": ("모니터",), "webcam": ("웹캠",), "microphone": ("마이크",),
    "speaker": ("스피커",), "bluetooth speaker": ("블루투스스피커",), "earphones": ("이어폰",), "earphone": ("이어폰",),
    "earbuds": ("이어폰", "이어버드"), "headphones": ("헤드폰",), "headphone": ("헤드폰",), "headset": ("헤드셋",),
    "wireless": ("무선",), "wired": ("유선",), "bluetooth": ("블루투스",), "charger": ("충전기",),
    "wireless charger": ("무선충전기",), "fast charging": ("고속충전",), "fast charger": ("고속충전기",),
    "charging cable": ("충전케이블",), "cable": ("케이블",), "usb cable": ("USB케이블",), "adapter": ("어댑터",),
    "power adapter": ("어댑터",), "power bank": ("보조배터리",), "power strip": ("멀티탭",), "extension cord": ("멀티탭", "연장선"),
    "hub": ("허브",), "usb hub": ("USB허브",), "card reader": ("카드리더기",), "memory card": ("메모리카드",),
    "flash drive": ("USB메모리",), "hard drive": ("하드디스크",), "ssd": ("SSD",), "router": ("공유기", "라우터"),
    "smart watch": ("스마트워치",), "smartwatch": ("스마트워치",), "watch": ("시계", "워치"), "watch band": ("시계줄", "워치밴드"),
    "watch strap": ("시계줄", "스트랩"), "strap": ("스트랩", "줄"), "band": ("밴드",), "camera": ("카메라",),
    "action camera": ("액션캠",), "tripod": ("삼각대",), "selfie stick": ("셀카봉",), "ring light": ("링라이트",),
    "gimbal": ("짐벌",), "drone": ("드론",), "projector": ("프로젝터", "빔프로젝터"), "remote": ("리모컨",),
    "remote control": ("리모컨",), "controller": ("컨트롤러",), "game controller": ("게임패드",), "gamepad": ("게임패드",),
    "console": ("콘솔",), "tv": ("TV", "티비"), "tv stand": ("TV스탠드",), "smart plug": ("스마트플러그",),
    "smart": ("스마트",), "sensor": ("센서",), "motion sensor": ("모션센서", "동작감지"), "doorbell": ("도어벨", "초인종"),
    "alarm": ("알람", "경보기"), "tracker": ("트래커",), "gps": ("GPS",), "walkie talkie": ("무전기",),
    "calculator": ("계산기",), "printer": ("프린터",), "label printer": ("라벨프린터",), "label": ("라벨",),
    "electric": ("전동", "전기"), "digital": ("디지털",), "portable": ("휴대용", "포터블"), "mini": ("미니",),
    "screen": ("화면", "스크린"), "display": ("디스플레이",), "touch": ("터치",), "waterproof": ("방수",),
    "shockproof": ("충격방지",), "dustproof": ("방진",), "anti slip": ("논슬립", "미끄럼방지"), "non slip": ("논슬립", "미끄럼방지"),
    "foldable": ("접이식", "폴더블"), "folding": ("접이식",), "adjustable": ("조절", "높이조절"), "rotating": ("회전",),
    "automatic": ("자동",), "manual": ("수동",), "multifunctional": ("다기능", "다용도"), "multifunction": ("다기능",),
    "multi purpose": ("다용도",), "universal": ("범용",), "heavy duty": ("고강도",), "large capacity": ("대용량",),
    "high capacity": ("대용량",), "capacity": ("용량",), "noise cancelling": ("노이즈캔슬링",), "noise canceling": ("노이즈캔슬링",),
    # materials
    "silicone": ("실리콘",), "silicon": ("실리콘",), "stainless": ("스텐", "스테인리스"), "stainless steel": ("스텐", "스테인리스"),
    "steel": ("스틸", "철제"), "metal": ("메탈", "금속"), "aluminum": ("알루미늄",), "aluminium": ("알루미늄",),
    "cast iron": ("주철", "무쇠"), "copper": ("구리", "동"), "brass": ("황동",), "titanium": ("티타늄",),
    "plastic": ("플라스틱",), "acrylic": ("아크릴",), "glass": ("유리", "글라스"), "ceramic": ("세라믹", "도자기"),
    "porcelain": ("도자기",), "wood": ("우드", "나무", "원목"), "wooden": ("우드", "원목", "나무"), "bamboo": ("대나무", "밤부"),
    "rattan": ("라탄",), "leather": ("가죽", "레더"), "pu leather": ("인조가죽", "PU가죽"), "fabric": ("패브릭", "원단"),
    "cotton": ("면", "코튼"), "linen": ("린넨",), "wool": ("울", "양모"), "fleece": ("플리스", "후리스"), "nylon": ("나일론",),
    "polyester": ("폴리에스터",), "mesh": ("메쉬", "망사"), "canvas": ("캔버스",), "denim": ("데님",), "rubber": ("고무",),
    "foam": ("폼", "스펀지"), "memory foam": ("메모리폼",), "latex": ("라텍스",), "gel": ("젤",), "paper": ("페이퍼", "종이"),
    "marble": ("마블", "대리석"), "crystal": ("크리스탈",), "resin": ("레진",), "felt": ("펠트",), "velvet": ("벨벳",),
    "carbon": ("카본",), "carbon fiber": ("카본",), "tpu": ("TPU",), "eva": ("EVA",), "pvc": ("PVC",),
    # colours
    "black": ("블랙", "검정"), "white": ("화이트", "흰색"), "red": ("레드", "빨강"), "blue": ("블루", "파랑"),
    "green": ("그린", "녹색"), "yellow": ("옐로우", "노랑"), "pink": ("핑크",), "purple": ("퍼플", "보라"),
    "gray": ("그레이", "회색"), "grey": ("그레이", "회색"), "brown": ("브라운", "갈색"), "beige": ("베이지",),
    "orange": ("오렌지", "주황"), "gold": ("골드",), "silver": ("실버",), "rose gold": ("로즈골드",), "navy": ("네이비",),
    "transparent": ("투명",), "clear": ("투명",), "ivory": ("아이보리",), "khaki": ("카키",), "mint": ("민트",),
    "colorful": ("컬러풀",), "color": ("컬러",), "colour": ("컬러",),
    # clothing, bags, accessories
    "bag": ("가방", "백"), "backpack": ("백팩",), "tote bag": ("토트백",), "shoulder bag": ("숄더백",), "crossbody bag": ("크로스백",),
    "wallet": ("지갑",), "card holder": ("카드지갑", "카드홀더"), "pouch": ("파우치",), "makeup bag": ("화장품파우치",),
    "belt": ("벨트",), "hat": ("모자",), "cap": ("캡모자", "모자"), "beanie": ("비니",), "scarf": ("스카프", "머플러"),
    "socks": ("양말",), "sock": ("양말",), "slippers": ("슬리퍼",), "slipper": ("슬리퍼",), "shoes": ("신발", "슈즈"), "shoe": ("신발",),
    "sneakers": ("스니커즈", "운동화"), "sandals": ("샌들",), "boots": ("부츠",), "insole": ("깔창", "인솔"),
    "shoelace": ("신발끈",), "shoelaces": ("신발끈",), "sunglasses": ("선글라스",), "glasses": ("안경",),
    "glasses case": ("안경케이스",), "necklace": ("목걸이",), "bracelet": ("팔찌",), "ring": ("반지", "링"),
    "earrings": ("귀걸이",), "earring": ("귀걸이",), "jewelry": ("쥬얼리", "악세사리"), "jewelry box": ("보석함", "쥬얼리박스"),
    "hair": ("헤어",), "hair clip": ("헤어핀", "머리핀"), "hair band": ("헤어밴드", "머리띠"), "hair tie": ("머리끈",),
    "scrunchie": ("곱창밴드", "머리끈"), "headband": ("헤어밴드", "머리띠"), "comb": ("빗",), "hair brush": ("헤어브러시", "빗"),
    "hair dryer": ("헤어드라이어", "드라이기"), "curler": ("고데기",), "straightener": ("고데기", "판고데기"),
    "shirt": ("셔츠",), "t shirt": ("티셔츠",), "tshirt": ("티셔츠",), "hoodie": ("후드티",), "sweater": ("스웨터", "니트"),
    "jacket": ("자켓",), "coat": ("코트",), "pants": ("팬츠", "바지"), "leggings": ("레깅스",), "shorts": ("반바지",),
    "dress": ("드레스", "원피스"), "skirt": ("스커트",), "underwear": ("언더웨어", "속옷"), "bra": ("브라",),
    "pajamas": ("파자마", "잠옷"), "swimsuit": ("수영복",), "raincoat": ("우비",), "vest": ("베스트", "조끼"),
    "men": ("남성",), "mens": ("남성",), "women": ("여성",), "womens": ("여성",), "unisex": ("남녀공용",),
    "kids": ("아동", "키즈"), "children": ("아동", "어린이"), "baby": ("아기", "유아", "베이비"), "toddler": ("유아",),
    # beauty, health
    "makeup": ("메이크업", "화장"), "cosmetic": ("화장품",), "cosmetics": ("화장품",), "makeup brush": ("메이크업브러시",), "puff": ("퍼프",), "makeup mirror": ("화장거울",), "eyelash": ("아이래시", "속눈썹"), "eyelashes": ("속눈썹",), "eyelash curler": ("뷰러",),
    "nail": ("네일",), "nail clipper": ("손톱깎이",), "nail file": ("네일파일",), "tweezers": ("족집게", "핀셋"),
    "razor": ("면도기",), "shaver": ("면도기",), "trimmer": ("트리머",), "epilator": ("제모기",), "massager": ("마사지기", "안마기"),
    "massage": ("마사지",), "massage gun": ("마사지건",), "foot massager": ("발마사지기",), "neck massager": ("목마사지기",),
    "heating pad": ("전기찜질기", "온열패드"), "hot pack": ("핫팩",), "ice pack": ("아이스팩", "냉찜질"),
    "posture corrector": ("자세교정밴드",), "knee brace": ("무릎보호대",), "wrist brace": ("손목보호대",),
    "wrist support": ("손목보호대",), "back support": ("허리보호대",), "insoles": ("깔창",), "eye mask": ("수면안대", "안대"),
    "sleep mask": ("수면안대",), "earplugs": ("귀마개",), "ear plugs": ("귀마개",), "mask": ("마스크",),
    "pill box": ("약통",), "pill organizer": ("약통",), "blood pressure": ("혈압",), "blood pressure monitor": ("혈압계",),
    "oximeter": ("산소포화도측정기",), "toothpaste": ("치약",), "floss": ("치실",), "water flosser": ("구강세정기",),
    "electric toothbrush": ("전동칫솔",), "skin care": ("스킨케어",), "face": ("페이스", "얼굴"), "facial": ("페이셜",),
    "face roller": ("페이스롤러",), "jade roller": ("옥롤러",), "cleansing": ("클렌징",), "serum": ("세럼",), "cream": ("크림",),
    "perfume": ("향수",), "perfume bottle": ("공병", "향수공병"), "atomizer": ("향수공병",), "hair removal": ("제모",),
    # sport, fitness
    "yoga": ("요가",), "yoga mat": ("요가매트",), "resistance band": ("밴드", "저항밴드"), "resistance bands": ("저항밴드",),
    "dumbbell": ("덤벨",), "dumbbells": ("덤벨",), "kettlebell": ("케틀벨",), "jump rope": ("줄넘기",), "skipping rope": ("줄넘기",),
    "foam roller": ("폼롤러",), "gym": ("헬스", "짐"), "fitness": ("피트니스", "헬스"), "sports": ("스포츠",),
    "running": ("러닝",), "cycling": ("사이클링", "자전거"), "bike": ("자전거",), "bicycle": ("자전거",), "bike light": ("자전거라이트",),
    "bike lock": ("자전거자물쇠",), "helmet": ("헬멧",), "shaker": ("쉐이커",),
    "swimming": ("수영",), "goggles": ("고글", "물안경"), "swim cap": ("수모",), "fishing": ("낚시",), "golf": ("골프",),
    "ball": ("볼", "공"), "football": ("축구공",), "soccer": ("축구",), "basketball": ("농구",), "badminton": ("배드민턴",),
    "grip": ("그립",), "hand grip": ("악력기",), "pedometer": ("만보기",), "hiking": ("등산", "하이킹"), "trekking pole": ("등산스틱",),
    # car
    "car": ("차량용", "자동차"), "auto": ("자동차",), "vehicle": ("차량",), "car charger": ("차량용충전기",),
    "car vacuum": ("차량용청소기",), "car organizer": ("차량용수납",), "car seat": ("카시트",), "seat cover": ("시트커버",),
    "steering wheel cover": ("핸들커버",), "dash cam": ("블랙박스",), "dashcam": ("블랙박스",), "air freshener": ("방향제",),
    "car air freshener": ("차량용방향제",), "windshield": ("앞유리",), "wiper": ("와이퍼",), "tire": ("타이어",),
    "tire pressure": ("타이어공기압",), "tire inflator": ("타이어공기주입기",), "air compressor": ("에어컴프레서",),
    "jump starter": ("점프스타터",), "sunshade": ("햇빛가리개",), "sun shade": ("햇빛가리개",), "trunk": ("트렁크",),
    "trunk organizer": ("트렁크정리함",), "cup holder": ("컵홀더",), "key": ("키",), "key chain": ("키링", "키홀더"),
    "keychain": ("키링", "키홀더"), "key case": ("키케이스",), "key holder": ("키홀더",), "parking": ("주차",),
    # pets, baby
    "pet": ("반려동물", "애견"), "dog": ("강아지", "애견"), "cat": ("고양이",), "puppy": ("강아지",), "pet bed": ("애견방석", "펫베드"),
    "pet bowl": ("애견식기",), "dog bowl": ("강아지식기",), "cat bowl": ("고양이식기",), "leash": ("리드줄",), "dog leash": ("강아지리드줄",),
    "harness": ("하네스",), "collar": ("목줄", "칼라"), "dog collar": ("강아지목줄",), "pet toy": ("애견장난감",), "toy": ("장난감",),
    "cat toy": ("고양이장난감",), "cat tree": ("캣타워",), "scratcher": ("스크래처",), "litter": ("모래",), "litter box": ("고양이화장실",),
    "pet brush": ("애견브러시",), "pet carrier": ("이동가방", "펫캐리어"), "feeder": ("급식기",), "water fountain": ("급수기",),
    "pet water fountain": ("반려동물급수기",), "poop bag": ("배변봉투",), "pee pad": ("배변패드",), "grooming": ("미용",),
    "bib": ("턱받이",), "pacifier": ("쪽쪽이", "공갈젖꼭지"), "baby bottle": ("젖병",), "teether": ("치발기",), "stroller": ("유모차",),
    "diaper": ("기저귀",), "diaper bag": ("기저귀가방",), "baby monitor": ("베이비모니터",), "rattle": ("딸랑이",),
    "building blocks": ("블록",), "blocks": ("블록",), "puzzle": ("퍼즐",), "doll": ("인형",), "plush": ("봉제인형", "인형"),
    "plush toy": ("봉제인형",), "stuffed animal": ("봉제인형",), "bath toy": ("목욕장난감",), "balloon": ("풍선",),
    # stationery, misc
    "pen": ("펜",), "pencil": ("연필",), "pencil case": ("필통",), "notepad": ("메모지",),
    "sticky notes": ("포스트잇",), "marker": ("마카",), "highlighter": ("형광펜",), "eraser": ("지우개",), "ruler": ("자",),
    "stapler": ("스테이플러",), "binder": ("바인더",), "folder": ("파일",), "envelope": ("봉투",), "calendar": ("캘린더",),
    "planner": ("플래너", "다이어리"), "diary": ("다이어리",), "bookmark": ("북마크", "책갈피"), "book stand": ("독서대",),
    "reading light": ("독서등",), "desk organizer": ("데스크정리함",), "pen holder": ("펜홀더", "연필꽂이"),
    "whiteboard": ("화이트보드",), "gift": ("선물",), "party": ("파티",), "decoration": ("장식", "데코"), "decor": ("데코", "장식"),
    "christmas": ("크리스마스",), "halloween": ("할로윈",), "birthday": ("생일",), "wedding": ("웨딩",), "travel": ("여행",),
    "travel pillow": ("여행용목베개", "목베개"), "neck pillow": ("목베개",), "luggage": ("캐리어",), "suitcase": ("캐리어",),
    "luggage tag": ("네임택",), "luggage strap": ("캐리어벨트",), "packing cubes": ("여행파우치",), "passport holder": ("여권지갑",),
    "toiletry bag": ("세면가방",), "portable fan": ("휴대용선풍기", "손선풍기"), "handheld fan": ("손선풍기",),
    "set": ("세트",), "kit": ("키트", "세트"), "pack": ("팩",), "pieces": ("개입",), "pcs": ("개입",), "pair": ("한쌍",),
    "size": ("사이즈",), "large": ("대형", "라지"), "small": ("소형", "스몰"), "medium": ("중형",), "long": ("롱",), "short": ("숏",),
    "thick": ("두꺼운",), "thin": ("슬림",), "slim": ("슬림",), "lightweight": ("경량",), "light weight": ("경량",),
    "premium": ("프리미엄",), "luxury": ("럭셔리",), "cute": ("귀여운",), "vintage": ("빈티지",), "simple": ("심플",),
    "modern": ("모던",), "korean": ("한국",), "japanese": ("일본",), "nordic": ("북유럽",), "home": ("홈", "가정용"),
    "household": ("가정용", "생활용품"), "office": ("사무용", "오피스"), "desktop": ("탁상", "데스크"), "wall": ("벽",),
    "wall mounted": ("벽걸이",), "hanging": ("걸이",), "handheld": ("핸디", "휴대용"), "cordless": ("무선",),
    "usb": ("USB",), "type c": ("C타입",), "usb c": ("C타입",), "lightning": ("라이트닝",), "micro usb": ("5핀",),
    "led": ("LED",), "rgb": ("RGB",), "hd": ("HD",), "4k": ("4K",), "1080p": ("1080p",),
    "heat resistant": ("내열",), "heat resistance": ("내열",), "cooking": ("요리", "쿠킹"), "cookware": ("조리도구",),
    "utensil": ("조리도구",), "utensils": ("조리도구",), "gadget": ("가젯", "용품"), "gadgets": ("용품",), "accessories": ("악세사리", "액세서리"),
    "accessory": ("악세사리",), "supplies": ("용품",), "tools": ("도구", "공구"), "device": ("기기",), "machine": ("기계", "머신"),
    "portable charger": ("보조배터리",), "reusable": ("재사용",), "disposable": ("일회용",), "eco friendly": ("친환경",),
    "food grade": ("식품용", "식품등급"), "bpa free": ("BPA프리",), "dishwasher safe": ("식기세척기사용가능",),
}

# Brand names as Korean shops spell them. Used to compare `Offer.brand` across languages.
_BRANDS: dict[str, str] = {
    "sony": "소니", "samsung": "삼성", "apple": "애플", "lg": "엘지", "xiaomi": "샤오미", "mi": "샤오미", "huawei": "화웨이",
    "anker": "앤커", "baseus": "베이스어스", "ugreen": "유그린", "logitech": "로지텍", "jbl": "제이비엘", "bose": "보스",
    "dyson": "다이슨", "philips": "필립스", "panasonic": "파나소닉", "braun": "브라운", "nike": "나이키", "adidas": "아디다스",
    "puma": "푸마", "lego": "레고", "disney": "디즈니", "nintendo": "닌텐도", "canon": "캐논", "nikon": "니콘", "gopro": "고프로",
    "dji": "디제이아이", "tefal": "테팔", "lock&lock": "락앤락", "locknlock": "락앤락", "zwilling": "즈윌링", "wmf": "더블유엠에프",
    "stanley": "스탠리", "yeti": "예티", "thermos": "써모스", "zojirushi": "조지루시", "tiger": "타이거", "oxo": "옥소",
    "joseph joseph": "조셉조셉", "ikea": "이케아", "muji": "무지", "daiso": "다이소", "kitchenaid": "키친에이드", "bruno": "브루노",
    "delonghi": "드롱기", "nespresso": "네스프레소", "bialetti": "비알레띠", "hario": "하리오", "kinto": "킨토",
    "3m": "3M", "duracell": "듀라셀", "energizer": "에너자이저", "tp-link": "티피링크", "tplink": "티피링크", "netgear": "넷기어",
    "razer": "레이저", "corsair": "커세어", "hyperx": "하이퍼엑스", "sennheiser": "젠하이저", "beats": "비츠", "marshall": "마샬",
}

_KOREAN = "가-힣"


def _key(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").replace("_", " ").split())


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


class Glossary:
    """English words and phrases -> Korean forms. Case- and plural-insensitive."""

    def __init__(self, terms: dict[str, tuple[str, ...]] | None = None, brands: dict[str, str] | None = None):
        self.terms = {_key(k): tuple(v) for k, v in (terms if terms is not None else _BUILTIN).items()}
        self.brands = {_key(k): v for k, v in (brands if brands is not None else _BRANDS).items()}
        self._longest = max((len(k.split()) for k in self.terms), default=1)

    def lookup(self, phrase: str) -> tuple[str, ...]:
        key = _key(phrase)
        forms = self.terms.get(key)
        if forms is None and " " not in key:
            forms = self.terms.get(_singular(key))
        return forms or ()

    def translate_phrases(self, words: list[str]) -> list[tuple[list[str], tuple[str, ...]]]:
        """Greedy longest-phrase-first translation of a token list. Unknown words are dropped.

        Returns (english words consumed, Korean forms) per matched phrase, in title order.
        """
        out: list[tuple[list[str], tuple[str, ...]]] = []
        i = 0
        while i < len(words):
            for n in range(min(self._longest, len(words) - i), 0, -1):
                forms = self.lookup(" ".join(words[i : i + n]))
                if forms:
                    out.append((words[i : i + n], forms))
                    i += n
                    break
            else:
                i += 1
        return out

    def translate(self, words: list[str]) -> list[tuple[str, ...]]:
        """Korean forms per matched English phrase, in title order."""
        return [forms for _, forms in self.translate_phrases(words)]

    def korean_query(self, words: list[str], max_terms: int = 6) -> str:
        """Korean search phrase: the preferred form of each translated word, in title order."""
        seen: dict[str, None] = {}
        for forms in self.translate(words):
            seen.setdefault(forms[0], None)
        return " ".join(list(seen)[:max_terms])

    def brand(self, name: str) -> str:
        """Canonical Korean brand spelling, or the name unchanged."""
        return self.brands.get(_key(name), name)

    def extended(self, path: str | Path) -> Glossary:
        """A copy with entries from a CSV (`english,korean`, forms split by `|`; a `brand:` prefix adds a brand)."""
        terms, brands = dict(self.terms), dict(self.brands)
        try:
            with Path(path).open(newline="", encoding="utf-8-sig") as f:
                for line, row in enumerate(csv.reader(f), start=1):
                    if not row or row[0].startswith("#") or (line == 1 and _key(row[0]) == "english"):
                        continue
                    if len(row) < 2 or not row[0].strip() or not row[1].strip():
                        raise ConfigError(f"{path}:{line}: expected 'english,korean'")
                    english, korean = row[0].strip(), row[1].strip()
                    if english.lower().startswith("brand:"):
                        brands[_key(english[6:])] = korean
                    else:
                        terms[_key(english)] = tuple(k.strip() for k in korean.split("|") if k.strip())
        except OSError as e:
            raise ConfigError(f"can't read glossary {path}: {e}") from e
        return Glossary(terms, brands)


DEFAULT = Glossary()


@lru_cache(maxsize=None)
def load(path: str | None = None) -> Glossary:
    """The built-in glossary, extended with `path` when given. Cached per path."""
    return DEFAULT.extended(path) if path else DEFAULT
