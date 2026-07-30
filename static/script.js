// script.js - Final Fixed Version (UI_TEXT Included)

console.log('SCRIPT_LOADED_FINAL_FIX');

// ==========================================
// [신규] 1. 스플래시 화면 로직
// ==========================================
window.addEventListener('load', () => {
    setTimeout(() => {
        const splash = document.getElementById('splash-screen');
        if (splash) {
            splash.classList.add('fade-out');
            setTimeout(() => {
                splash.remove();
            }, 600);
        }
    }, 1500);
});

// --- 1. 전역 변수 ---
const chatBox = document.getElementById('chat-box');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const micBtn = document.getElementById('mic-btn');

const API_URL_CHAT = '/chat';
const API_URL_RESULT = '/get_result/';
const API_URL_FEEDBACK = '/feedback';

let safetyTimeoutId = null;
let placeholderIntervalId = null;

let currentResultIds = [];
let currentShownCount = 0;
let currentTotalFound = 0;

let pendingContext = null;
let currentQuestion = "";
let chatHistory = [];
const MAX_HISTORY_TURNS = 2;

// ============================================================
// [★핵심] 다국어 데이터베이스 (UI_TEXT) - 꿀팁 통합됨
// ============================================================
const UI_TEXT = {
    ko: {
        loading: "답변을 생성하고 있습니다",
        actions: [
            "🔍 질문의 의도를 꼼꼼히 분석하고 있어요...",
            "📂 영유아 복지 데이터베이스를 꼼꼼히 살피는 중...",
            "🏃‍♀️ 관련 문서를 찾아 열심히 뛰어다니는 중...",
            "🤔 자격 요건이 맞는지 확인하고 있어요...",
            "📝 찾은 정보를 보기 좋게 요약하는 중...",
            "✨ 답변을 예쁘게 포장하고 있어요..."
        ],
        tips: [
            // [기존 한국어 꿀팁 그대로 유지]
            "[0~12개월] 터미타임의 기적: 생후 1개월부터 깨어있을 때 엎드려 놀게 해주세요. 등 근육이 튼튼해집니다.",
            "[0~12개월] 초점 책보다 엄마 얼굴: 아기가 가장 좋아하는 장난감은 부모의 눈과 입입니다. 눈을 맞춰주세요.",
            "[0~12개월] 울음은 대화예요: 아기가 울 때 즉각 반응해 주세요. 세상에 대한 신뢰가 쌓입니다.",
            "[0~12개월] 까꿍 놀이의 힘: 6개월부터 까꿍 놀이를 해주세요. 대상 영속성을 배웁니다.",
            "[0~12개월] 전신 마사지: 기저귀 갈 때 다리를 쭉쭉 펴주는 마사지는 성장판을 자극합니다.",
            "[0~12개월] 옹알이 리액션: 아기가 '아~' 하면 엄마도 따라 해주세요. 대화의 즐거움을 배웁니다.",
            "[0~12개월] 이유식은 촉감 놀이: 아이가 음식을 손으로 만지고 뭉개도 괜찮아요. 오감 발달 과정입니다.",
            "[0~12개월] 안전한 탐색: 기어 다니기 시작하면 바닥의 작은 물건은 치워주세요. 구강기 사고 예방!",
            "[13~36개월] '내가 할래!' 존중하기: 서툴러도 혼자 해보게 기다려주세요. 자존감이 자라납니다.",
            "[13~36개월] 언어 확장하기: '물'이라고 하면 '시원한 물 줄까?'라고 문장으로 늘려 말해주세요.",
            "[13~36개월] 스티커 놀이: 손가락 끝으로 스티커를 떼고 붙이는 놀이는 소근육 발달에 최고입니다.",
            "[13~36개월] 감정 읽어주기: 떼쓸 땐 혼내기보다 '속상했구나'라고 감정을 먼저 읽어주세요.",
            "[13~36개월] 선택권 주기: '양말 신어' 대신 '파란 양말 줄까, 빨간 양말 줄까?'라고 물어보세요.",
            "[13~36개월] 배변 훈련 타이밍: 아이가 기저귀 젖는 것을 불편해하거나 화장실에 관심을 보일 때가 적기입니다.",
            "[13~36개월] 미디어 프리: 만 2세 이전에는 영상 노출을 피하는 것이 뇌 발달에 가장 좋습니다.",
            "[13~36개월] 역할 놀이: 인형에게 밥을 먹이는 흉내를 내보세요. 상상력과 공감 능력이 자랍니다.",
            "[13~36개월] 잠자리 독서: 자기 전 그림책 한 권은 수면 의식이 되고 언어 발달도 돕습니다.",
            "[13~36개월] 위험할 땐 단호하게: 안전 문제는 길게 설명하지 말고 짧고 단호하게 '안 돼'라고 말해주세요.",
            "[37~72개월] 호기심 대장: 끊임없는 '왜?' 질문에 '너는 어떻게 생각해?'라고 되물어 사고력을 키워주세요.",
            "[37~72개월] 규칙 있는 놀이: 술래잡기나 보드게임을 통해 규칙을 지키고 순서를 기다리는 법을 알려주세요.",
            "[37~72개월] 구체적인 칭찬: '착하네' 대신 '장난감을 제자리에 정리해서 멋지다'라고 구체적으로 칭찬해 주세요.",
            "[37~72개월] 거짓말 대처: 만 4세의 거짓말은 상상의 혼동일 수 있습니다. 혼내기보다 사실을 말하게 유도하세요.",
            "[37~72개월] 감정 단어: '화나' 외에도 '서운해, 억울해, 부끄러워' 등 다양한 감정 단어를 알려주세요.",
            "[37~72개월] 과정 칭찬: 결과보다 과정을 칭찬하면 새로운 도전을 두려워하지 않는 아이가 됩니다.",
            "[37~72개월] 디지털 약속: 영상은 하루 1시간 이내로, 아이와 함께 규칙을 정해서 보세요.",
            "[37~72개월] 성교육의 시작: 신체 부위의 명칭을 알려주고, '내 몸의 주인은 나'라는 것을 가르쳐주세요.",
            "[37~72개월] 스스로 해결: 친구와 다퉜을 때 아이가 어떻게 해결하고 싶은지 먼저 물어봐 주세요.",
            "[37~72개월] 작은 심부름: 수저 놓기 등 집안일에 참여시켜 가족 구성원으로서의 소속감을 느끼게 해주세요.",
            "[부모 꿀팁] 비교 금지: 옆집 아이와 비교하지 마세요. 우리 아이만의 속도가 있습니다.",
            "[부모 꿀팁] 일관성: 부모의 기분에 따라 훈육 기준이 바뀌면 아이는 혼란스러워합니다.",
            "[부모 꿀팁] 부모의 사과: 부모도 실수할 수 있습니다. 솔직하게 사과하는 모습은 최고의 교육입니다.",
            "[부모 꿀팁] 경청: 아이가 말을 더듬더라도 끝까지 들어주세요. 말하는 자신감이 생깁니다.",
            "[부모 꿀팁] 눈높이 대화: 아이와 대화할 때는 무릎을 굽혀 아이의 눈높이에서 바라봐 주세요.",
            "[부모 꿀팁] 사랑의 스킨십: 하루 한 번, 아이를 꽉 안아주세요. 백 마디 말보다 큰 안정감을 줍니다.",
            "[부모 꿀팁] 충분히 좋은 부모: 완벽한 부모가 되려 하지 마세요. 지금도 충분히 잘하고 계십니다.",
            "[부모 꿀팁] 부모의 행복: 부모가 행복해야 아이도 행복합니다. 나를 위한 휴식 시간도 꼭 챙기세요.",
            "[부모 꿀팁] 잠이 보약: 성장 호르몬은 밤 10시~새벽 2시에 나옵니다. 일찍 재우는 습관을 들이세요.",
            "[부모 꿀팁] 식사 예절: 돌아다니며 먹지 않고 식탁에 앉아서 먹는 습관은 이유식 시기부터 잡아주세요.",
            "[부모 꿀팁] 자연 놀이터: 하루 30분, 바깥바람을 쐬게 해주세요. 면역력과 정서 발달에 좋습니다.",
            "[부모 꿀팁] 기다림의 미학: 육아의 8할은 기다림입니다. 아이가 스스로 해낼 때까지 한 템포만 기다려주세요."
        ]
    },
    en: {
        loading: "Generating answer",
        actions: [
            "🔍 Analyzing your question...",
            "📂 Searching the welfare database...",
            "🏃‍♀️ Finding relevant documents...",
            "🤔 Checking eligibility requirements...",
            "📝 Summarizing information...",
            "✨ Finalizing the answer..."
        ],
        tips: [
            // [영어 번역 완료]
            "[0-12m] Tummy Time: Let them play on their stomach when awake. Strengthens back muscles.",
            "[0-12m] Mom's Face: Baby's favorite toy is parents' eyes and mouth. Make eye contact.",
            "[0-12m] Crying is Communication: Respond immediately. Builds trust in the world.",
            "[0-12m] Peekaboo: Play from 6 months. Teaches object permanence.",
            "[0-12m] Massage: Stretching legs during diaper changes stimulates growth plates.",
            "[0-12m] Babbling: If baby says 'Ah~', copy them. Teaches joy of conversation.",
            "[0-12m] Messy Eating: Touching and squashing food is fine. It's sensory development.",
            "[0-12m] Safe Exploration: Clear small objects when crawling starts. Prevent choking!",
            "[13-36m] Respect 'I can do it': Wait even if clumsy. Self-esteem grows.",
            "[13-36m] Expand Language: If they say 'Water', say 'Do you want cold water?'.",
            "[13-36m] Sticker Play: Peeling and sticking develops fine motor skills.",
            "[13-36m] Read Emotions: Instead of scolding tantrums, say 'You must be upset'.",
            "[13-36m] Give Choices: 'Blue socks or red socks?' instead of 'Put on socks'.",
            "[13-36m] Potty Training: Best when they dislike wet diapers or show interest in the toilet.",
            "[13-36m] Media Free: Avoid screens before age 2 for best brain development.",
            "[13-36m] Role Play: Pretend to feed dolls. Imagination and empathy grow.",
            "[13-36m] Bedtime Reading: One book before sleep becomes a ritual and helps language.",
            "[13-36m] Firm on Danger: Don't explain long, just say 'No' short and firm.",
            "[37-72m] Curiosity: Ask 'What do you think?' back to 'Why?' questions.",
            "[37-72m] Rule Play: Tag or board games teach rules and waiting turns.",
            "[37-72m] Specific Praise: 'Great job cleaning up toys' instead of just 'Good boy'.",
            "[37-72m] Lying: At age 4, imagination confuses reality. Encourage truth instead of scolding.",
            "[37-72m] Emotion Words: Teach 'Sad, Unfair, Shy' beyond just 'Angry'.",
            "[37-72m] Praise Effort: Praising the process makes kids fear challenges less.",
            "[37-72m] Digital Rules: Under 1 hour/day, set rules together.",
            "[37-72m] Sex Ed: Teach body part names and 'I am the owner of my body'.",
            "[37-72m] Self Solving: Ask 'How do you want to solve it?' when fighting with friends.",
            "[37-72m] Chores: Setting spoons helps them feel like a helpful family member.",
            "[Parenting] No Comparison: Every child has their own speed. Don't compare.",
            "[Parenting] Consistency: Changing discipline based on mood confuses the child.",
            "[Parenting] Apology: Parents make mistakes too. Apologizing is great education.",
            "[Parenting] Listening: Listen until the end even if they stutter. Builds confidence.",
            "[Parenting] Eye Level: Bend knees to look at eye level when talking.",
            "[Parenting] Hugs: Hug tight once a day. Gives huge stability.",
            "[Parenting] Good Enough: Don't try to be perfect. You are doing well enough.",
            "[Parenting] Happy Parent: Happy parent = happy child. Take rest for yourself.",
            "[Parenting] Sleep: Growth hormones come 10pm-2am. Sleep early.",
            "[Parenting] Etiquette: Sitting to eat starts from solid food age.",
            "[Parenting] Nature: 30 mins outside a day. Good for immunity and emotions.",
            "[Parenting] Waiting: 80% of parenting is waiting. Wait one beat for them to do it."
        ]
    },
    vi: {
        loading: "Đang tạo câu trả lời",
        actions: [
            "🔍 Đang phân tích câu hỏi...",
            "📂 Đang tìm kiếm dữ liệu...",
            "🏃‍♀️ Đang tìm tài liệu...",
            "🤔 Đang kiểm tra điều kiện...",
            "📝 Đang tóm tắt thông tin...",
            "✨ Đang hoàn thiện..."
        ],
        tips: [
            // [베트남어 번역 완료]
            "[0-12m] Tummy Time: Cho bé nằm sấp khi thức. Giúp cơ lưng khỏe mạnh.",
            "[0-12m] Hơn cả sách: Đồ chơi thích nhất của bé là mắt và miệng cha mẹ.",
            "[0-12m] Khóc là giao tiếp: Hãy phản hồi ngay khi bé khóc để xây dựng niềm tin.",
            "[0-12m] Ú òa: Chơi từ 6 tháng tuổi giúp bé hiểu về sự tồn tại của vật thể.",
            "[0-12m] Mát-xa: Vuốt duỗi chân khi thay tã giúp kích thích sụn tăng trưởng.",
            "[0-12m] Tiếng bi bô: Bé nói 'A~' thì mẹ bắt chước theo. Niềm vui hội thoại.",
            "[0-12m] Ăn dặm là xúc giác: Bé bốc thức ăn cũng không sao. Phát triển ngũ quan.",
            "[0-12m] Khám phá an toàn: Dọn dẹp vật nhỏ trên sàn khi bé biết bò. Phòng hóc dị vật!",
            "[13-36m] Tôn trọng 'Con tự làm': Hãy kiên nhẫn đợi dù bé làm vụng. Lòng tự trọng tăng.",
            "[13-36m] Mở rộng ngôn ngữ: Bé nói 'Nước', hãy nói 'Con muốn uống nước mát hả?'.",
            "[13-36m] Dán hình: Bóc và dán sticker giúp phát triển cơ nhỏ ở tay.",
            "[13-36m] Đọc cảm xúc: Thay vì mắng khi bé ăn vạ, hãy nói 'Con buồn bực à'.",
            "[13-36m] Cho lựa chọn: Thay vì 'Đi tất vào', hãy hỏi 'Tất xanh hay đỏ?'.",
            "[13-36m] Bỏ tã: Thích hợp nhất khi bé khó chịu với tã ướt hoặc thích toilet.",
            "[13-36m] Không điện tử: Tránh màn hình trước 2 tuổi tốt nhất cho não.",
            "[13-36m] Đóng vai: Giả vờ cho búp bê ăn. Tăng trí tưởng tượng và đồng cảm.",
            "[13-36m] Đọc sách tối: Một cuốn sách mỗi tối giúp bé ngủ ngon và giỏi ngôn ngữ.",
            "[13-36m] Kiên quyết khi nguy hiểm: Đừng giải thích dài, hãy nói ngắn 'Không được'.",
            "[37-72m] Tò mò: Bé hỏi 'Tại sao?', hãy hỏi lại 'Con nghĩ thế nào?'.",
            "[37-72m] Quy tắc: Trò chơi có luật giúp bé học cách tuân thủ và chờ đợi.",
            "[37-72m] Khen cụ thể: Thay vì 'Ngoan quá', hãy khen 'Con dọn đồ chơi gọn gàng'.",
            "[37-72m] Nói dối: Trẻ 4 tuổi hay nhầm lẫn tưởng tượng. Hãy khuyến khích nói thật.",
            "[37-72m] Từ vựng cảm xúc: Dạy bé từ 'Tủi thân, Xấu hổ' ngoài từ 'Giận'.",
            "[37-72m] Khen quá trình: Khen nỗ lực giúp bé không sợ thử thách.",
            "[37-72m] Quy tắc điện tử: Dưới 1 tiếng/ngày, cùng bé đặt quy tắc.",
            "[37-72m] Giáo dục giới tính: Dạy tên bộ phận cơ thể và 'Cơ thể là của con'.",
            "[37-72m] Tự giải quyết: Khi cãi nhau, hỏi bé muốn giải quyết thế nào.",
            "[37-72m] Việc vặt: Nhờ bé xếp thìa đũa để bé thấy mình có ích.",
            "[Cha mẹ] Không so sánh: Đừng so với trẻ khác. Con có tốc độ riêng.",
            "[Cha mẹ] Nhất quán: Thay đổi tiêu chuẩn theo tâm trạng sẽ làm bé rối.",
            "[Cha mẹ] Xin lỗi: Bố mẹ cũng có thể sai. Xin lỗi là bài học tuyệt vời.",
            "[Cha mẹ] Lắng nghe: Nghe đến cùng dù bé nói lắp. Bé sẽ tự tin hơn.",
            "[Cha mẹ] Ngang tầm mắt: Khi nói chuyện, hãy ngồi xuống ngang mắt bé.",
            "[Cha mẹ] Cái ôm: Ôm chặt một lần mỗi ngày. Mang lại cảm giác an toàn.",
            "[Cha mẹ] Cha mẹ đủ tốt: Đừng cố hoàn hảo. Bạn đang làm đủ tốt rồi.",
            "[Cha mẹ] Cha mẹ hạnh phúc: Bố mẹ vui thì con mới vui. Hãy nghỉ ngơi.",
            "[Cha mẹ] Ngủ là thuốc bổ: Hormone tăng trưởng ra lúc 10h tối-2h sáng. Ngủ sớm.",
            "[Cha mẹ] Nết ăn: Ngồi ghế ăn, không chạy lung tung từ tuổi ăn dặm.",
            "[Cha mẹ] Thiên nhiên: 30 phút ngoài trời mỗi ngày. Tốt cho miễn dịch.",
            "[Cha mẹ] Chờ đợi: 80% nuôi con là chờ đợi. Hãy đợi một nhịp để bé làm."
        ]
    },
    zh: {
        loading: "正在生成答案",
        actions: [
            "🔍 正在分析提问...",
            "📂 正在搜索数据库...",
            "🏃‍♀️ 正在查找文档...",
            "🤔 正在确认资格...",
            "📝 正在总结信息...",
            "✨ 正在生成回答..."
        ],
        tips: [
            // [중국어 번역 완료]
            "[0-12m] 俯卧抬头: 满月后醒着时让宝宝趴着玩。能锻炼背部肌肉。",
            "[0-12m] 比起黑白卡: 宝宝最好的玩具是父母的眼睛和嘴巴。",
            "[0-12m] 哭泣是对话: 宝宝哭时请立即回应。建立信任感。",
            "[0-12m] 躲猫猫: 6个月起玩躲猫猫。学习客体永久性。",
            "[0-12m] 全身按摩: 换尿布时伸展腿部能刺激生长板。",
            "[0-12m] 咿呀学语: 宝宝发“啊~”时妈妈也跟着学。体会对话乐趣。",
            "[0-12m] 辅食触觉: 用手抓捏食物也没关系。这是五感发育。",
            "[0-12m] 安全探索: 开始爬行后清理地板小物。预防异物吞咽！",
            "[13-36m] 尊重“我自己来”: 即使笨拙也请等待。自尊心由此萌芽。",
            "[13-36m] 语言扩展: 宝宝说“水”，你可以说“要喝凉水吗？”。",
            "[13-36m] 贴纸游戏: 撕贴贴纸是锻炼小肌肉的最佳方式。",
            "[13-36m] 读懂情绪: 耍赖时别骂，先说“原来你很难过啊”。",
            "[13-36m] 给选择权:与其说“穿袜子”，不如问“穿蓝袜还是红袜？”。",
            "[13-36m] 如厕训练: 宝宝排斥湿尿布或对马桶感兴趣时最合适。",
            "[13-36m] 远离屏幕: 2岁前避免接触视频对大脑发育最好。",
            "[13-36m] 角色扮演: 假装给娃娃喂饭。想象力和共情力增长。",
            "[13-36m] 睡前阅读: 睡前一绘本能成为睡眠仪式，助语言发育。",
            "[13-36m] 危险时果断: 安全问题别长篇大论，短促有力说“不行”。",
            "[37-72m] 好奇心: 面对“为什么”，反问“你是怎么想的？”。",
            "[37-72m] 规则游戏: 捉迷藏或桌游教会孩子遵守规则。",
            "[37-72m] 具体表扬: 与其说“真棒”，不如说“玩具收拾得真整齐”。",
            "[37-72m] 应对撒谎: 4岁的谎言可能是想象混淆。鼓励说出事实。",
            "[37-72m] 情绪词汇: 除了“生气”，教教“委屈、遗憾”等词。",
            "[37-72m] 表扬过程: 表扬努力的过程，孩子才不会畏惧挑战。",
            "[37-72m] 电子约定: 每天1小时内，一起制定观看规则。",
            "[37-72m] 性教育: 告知身体部位名称，教导“我是身体的主人”。",
            "[37-72m] 自己解决: 争吵时，先问问孩子想怎么解决。",
            "[37-72m] 小跑腿: 让孩子摆勺子，感受家庭归属感。",
            "[父母] 禁止比较: 别跟别人比。每个孩子都有自己的速度。",
            "[父母] 一致性: 父母随心情改变标准，孩子会混乱。",
            "[父母] 父母的道歉: 父母也会犯错。坦率道歉是最好的教育。",
            "[父母] 倾听: 即使孩子说话结巴也要听完。培养自信。",
            "[父母] 视线高度: 对话时弯下膝盖，看着孩子的眼睛。",
            "[父母] 爱的拥抱: 每天用力抱一次。比千言万语更具安全感。",
            "[父母] 足够好的父母: 别追求完美。你已经做得足够好了。",
            "[父母] 父母的幸福: 父母幸福孩子才幸福。留出休息时间。",
            "[父母] 睡眠是补药: 生长激素晚10点-早2点分泌。早睡。",
            "[父母] 进餐礼仪: 坐着吃不乱跑，从辅食期就要抓起。",
            "[父母] 大自然: 每天30分钟户外。对免疫力和情绪极好。",
            "[父母] 等待的美学: 育儿八成是等待。慢一拍，等孩子自己做。"
        ]
    }
};

const SHOW_MORE_KEYWORDS = new Set([
    "다음", "더", "더 보여줘", "계속", "이어서", "다음거", "다음꺼", "다른거", "다른 거", "또",
    "next", "more", "continue", "show more",
    "tiếp", "thêm", "xem thêm", "nữa", "tiếp tục",
    "更多", "继续", "下", "下一个", "还有吗"
]);

// --- 2. 음성 인식 설정 ---
const isInIframe = window.self !== window.top;
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const canUseMic = SpeechRecognition && !isInIframe;

// --- 3. 버튼 토글 ---
function toggleInputButtons() {
    const text = userInput.value.trim();
    if (text.length > 0) {
        sendBtn.style.display = 'flex';
        micBtn.style.display = 'none';
    } else {
        if (canUseMic) {
            sendBtn.style.display = 'none';
            micBtn.style.display = 'flex';
        } else {
            sendBtn.style.display = 'flex';
            micBtn.style.display = 'none';
        }
    }
}
toggleInputButtons();
userInput.addEventListener('input', toggleInputButtons);

// --- 4. 이벤트 리스너 ---
sendBtn.addEventListener('click', () => {
    handleFormSubmit();
    setTimeout(toggleInputButtons, 10);
});

userInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    if (this.scrollHeight > 120) {
        this.style.overflowY = "auto";
    } else {
        this.style.overflowY = "hidden";
    }
    toggleInputButtons();
});

userInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
        if (!event.shiftKey) {
            event.preventDefault();
            if (event.isComposing) return;
            handleFormSubmit();
            setTimeout(() => {
                userInput.style.height = 'auto';
                toggleInputButtons();
            }, 10);
        }
    }
});

chatBox.addEventListener('click', async (event) => {
    if (event.target.classList.contains('clarify-btn')) {
        const buttonText = event.target.innerText;
        handleButtonClick(buttonText);
    }
    if (event.target.classList.contains('card-share-btn')) {
        const btn = event.target;
        const textToCopy = btn.dataset.copy;

        if (navigator.share && !isInIframe) {
            try {
                await navigator.share({ title: '복지 정보', text: textToCopy, url: window.location.href });
                return;
            } catch (err) { }
        }
        try {
            await navigator.clipboard.writeText(textToCopy);
            showToast("카드 내용이 복사되었습니다! ✅");
        } catch (err) {
            prompt("복사하기:", textToCopy);
        }
    }
});


// --- 5. 메인 로직 ---
async function handleFormSubmit() {
    const question = userInput.value.trim();
    if (!question) return;

    pendingContext = null;
    currentQuestion = question;
    clearButtons();
    updateChatHistory("user", question);
    setLoadingState(true);

    let serverQuestion = question;
    if (window.currentLang === 'en') {
        serverQuestion += " \n\n(System: Please answer strictly in English.)";
    } else if (window.currentLang === 'vi') {
        serverQuestion += " \n\n(System: Please answer strictly in Vietnamese.)";
    } else if (window.currentLang === 'zh') {
        serverQuestion += " \n\n(System: Please answer strictly in Chinese.)";
    }

    let requestBody = {
        question: serverQuestion,
        language: window.currentLang || 'ko',
        last_result_ids: [],
        shown_count: 0,
        chat_history: chatHistory
    };

    if (SHOW_MORE_KEYWORDS.has(question.toLowerCase())) {
        requestBody.last_result_ids = currentResultIds;
        requestBody.shown_count = currentShownCount;
    }

    addMessageToBox('user', question);
    userInput.value = '';
    toggleInputButtons();

    await fetchChatResponse(requestBody);
}

async function handleButtonClick(buttonText) {
    let newQuestion = pendingContext ? `${pendingContext} ${buttonText}` : buttonText;
    pendingContext = null;
    clearButtons();
    addMessageToBox('user', newQuestion);
    currentQuestion = newQuestion;
    updateChatHistory("user", newQuestion);
    setLoadingState(true);

    let serverQuestion = newQuestion;
    if (window.currentLang === 'en') {
        serverQuestion += " \n\n(System: Please answer strictly in English.)";
    } else if (window.currentLang === 'vi') {
        serverQuestion += " \n\n(System: Please answer strictly in Vietnamese.)";
    } else if (window.currentLang === 'zh') {
        serverQuestion += " \n\n(System: Please answer strictly in Chinese.)";
    }

    const requestBody = {
        question: serverQuestion,
        language: window.currentLang || 'ko',
        last_result_ids: [],
        shown_count: 0,
        chat_history: chatHistory
    };
    await fetchChatResponse(requestBody);
}

// --- 7. Typewriter Effect (Streaming Emulation) ---
async function typeWriterEffect(element, htmlContent) {
    // 1. 기존 내용 비우기 (로딩 애니메이션 제거)
    element.innerHTML = "";

    // 2. HTML을 임시 태그에 넣어 텍스트 노드와 엘리먼트 노드로 분리
    // (복잡한 HTML 구조를 유지하면서 타이핑하는 것은 매우 어려우므로,
    //  단순 텍스트는 타이핑하고, 태그(카드 등)는 통째로 페이드인 하는 방식을 사용)

    // 만약 "결과 카드(result-card)"가 포함된 복잡한 HTML이라면
    // 타이핑 효과보다는 부드러운 페이드인(Fade-in)이 더 적합할 수 있음.
    // 하지만 요청대로 "글자" 위주의 타이핑 효과를 구현하되, 태그가 깨지지 않게 처리함.

    if (htmlContent.includes("result-card")) {
        // 카드가 포함된 경우: 그냥 페이드인으로 처리 (타이핑하면 카드 레이아웃이 깨짐)
        element.style.opacity = 0;
        element.innerHTML = htmlContent;

        // CSS transition을 이용한 페이드인
        element.style.transition = "opacity 0.5s ease-in";
        requestAnimationFrame(() => {
            element.style.opacity = 1;
        });
        return;
    }

    // 일반 텍스트/마크다운 응답인 경우:
    // HTML 파싱
    const tempDiv = document.createElement("div");
    tempDiv.innerHTML = htmlContent;

    const nodes = Array.from(tempDiv.childNodes);
    element.style.opacity = 1; // 보이게 설정

    for (const node of nodes) {
        if (node.nodeType === Node.TEXT_NODE) {
            // 텍스트 노드: 한 글자씩 타이핑
            const text = node.textContent;
            for (let i = 0; i < text.length; i++) {
                element.append(text[i]);

                // [Smart Scroll] 사용자가 바닥에 있을 때만 스크롤 (읽으려고 올려뒀으면 방해 X)
                if (chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight < 100) {
                    chatBox.scrollTop = chatBox.scrollHeight;
                }

                await new Promise(r => setTimeout(r, 15)); // 속도 조절 (15ms)
            }
        } else {
            // 엘리먼트 노드: 통째로 붙임
            element.appendChild(node.cloneNode(true));

            // [Smart Scroll]
            if (chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight < 100) {
                chatBox.scrollTop = chatBox.scrollHeight;
            }

            await new Promise(r => setTimeout(r, 50)); // 태그 간 딜레이
        }
    }
}

async function fetchChatResponse(requestBody) {
    const lang = window.currentLang || 'ko';

    // [수정] 꿀팁이 없을 경우를 대비한 안전장치
    const langData = UI_TEXT[lang] || UI_TEXT['ko'];
    const actionMessages = langData.actions;
    const currentTips = langData.tips || UI_TEXT['ko'].tips; // 팁이 비어있으면 한국어 사용

    const initialMsg = actionMessages[0];
    const rawInitialTip = currentTips[Math.floor(Math.random() * currentTips.length)];
    const formattedInitialTip = rawInitialTip.replace(': ', ':<br>');

    // ... (기존 로딩 스켈레톤 코드 유지)
    const skeletonHTML = `
        <div class="skeleton-container">
            <div class="skeleton-box" style="width: 90%;"></div>
            <div class="skeleton-box" style="width: 70%;"></div>
            <div class="skeleton-box" style="width: 85%;"></div>
            
            <div style="margin-top: 12px;">
                <div style="margin-top: 12px; text-align: left;"> <p class="action-text" style="font-size: 14px; font-weight: 600; color: #333; margin: 0 0 8px 0;">
                    ${initialMsg}
                </p>
                <p class="tip-text" style="font-size: 12px; font-weight: 400; color: #888; margin: 0; line-height: 1.6;">
                    ${formattedInitialTip}
                </p>
            </div>
        </div>
    `;

    const loadingElement = addMessageToBox('assistant', skeletonHTML);
    const actionTextEl = loadingElement.querySelector('.action-text');
    const tipTextEl = loadingElement.querySelector('.tip-text');

    let toggleStep = 0;
    let messageIntervalId = setInterval(() => {
        toggleStep++;

        if (toggleStep % 2 === 0) {
            const actionIndex = (toggleStep / 2) % actionMessages.length;
            if (actionTextEl) actionTextEl.textContent = actionMessages[actionIndex];
        } else {
            const randomTip = currentTips[Math.floor(Math.random() * currentTips.length)];
            if (tipTextEl) {
                tipTextEl.innerHTML = randomTip.replace(': ', ':<br>');
            }
        }
    }, 7000);

    try {
        const chatResponse = await fetch(API_URL_CHAT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        if (!chatResponse.ok) throw new Error(`Server error: ${chatResponse.statusText}`);
        const chatData = await chatResponse.json();

        if (chatData.status === 'clarify') {
            clearInterval(messageIntervalId);

            // [적용] 타이핑 효과
            const parsedHTML = marked.parse(chatData.answer);
            await typeWriterEffect(loadingElement, parsedHTML);

            pendingContext = currentQuestion;
            createButtons(chatData.options);
            updateChatHistory("assistant", chatData.answer);
            setLoadingState(false);
        }
        else if (chatData.status === 'complete' || chatData.status === 'error') {
            clearInterval(messageIntervalId);

            let finalHTML = "";
            if (chatData.answer.includes('result-card')) {
                finalHTML = chatData.answer;
            } else {
                finalHTML = marked.parse(chatData.answer);
            }

            // [적용] 타이핑 효과 (카드면 페이드인, 텍스트면 타이핑)
            await typeWriterEffect(loadingElement, finalHTML);

            currentResultIds = chatData.last_result_ids || [];
            currentTotalFound = chatData.total_found || 0;
            currentShownCount = chatData.shown_count || Math.min(2, currentResultIds.length);
            updateChatHistory("assistant", chatData.answer);

            if (chatData.job_id) {
                addFeedbackButtons(loadingElement, chatData.job_id, currentQuestion, chatData.answer);
            }
            setLoadingState(false);
        }
        else if (chatData.job_id) {
            const jobId = chatData.job_id;
            pollForResult(jobId, currentQuestion, loadingElement, messageIntervalId, actionTextEl, tipTextEl);
        }
    } catch (error) {
        loadingElement.innerHTML = `<p>오류 발생: ${error.message}</p>`;
        if (messageIntervalId) clearInterval(messageIntervalId);
        setLoadingState(false);
    }
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function pollForResult(jobId, question, loadingElement, messageIntervalId, actionTextEl, tipTextEl, pollInterval = 1000) {
    let attempts = 0;
    const intervalId = setInterval(async () => {
        attempts++;
        if (attempts > 120) {
            clearInterval(intervalId); clearInterval(messageIntervalId);
            loadingElement.innerHTML = '<p>시간 초과</p>';
            setLoadingState(false);
            return;
        }
        try {
            const resultResponse = await fetch(`${API_URL_RESULT}${jobId}`);
            if (!resultResponse.ok) return;
            const resultData = await resultResponse.json();

            if (resultData.status === 'complete') {
                clearInterval(intervalId); clearInterval(messageIntervalId);

                let finalHTML = "";
                if (resultData.answer.includes('result-card')) {
                    finalHTML = resultData.answer;
                } else {
                    finalHTML = marked.parse(resultData.answer);
                }

                // [적용] 타이핑 효과
                await typeWriterEffect(loadingElement, finalHTML);

                translateCardButtons(loadingElement);

                updateChatHistory("assistant", resultData.answer);
                currentResultIds = resultData.last_result_ids || [];
                currentTotalFound = resultData.total_found || 0;
                currentShownCount = Math.min(2, currentResultIds.length);

                addFeedbackButtons(loadingElement, jobId, question, resultData.answer);
                setLoadingState(false);
            } else if (resultData.status === 'error') {
                clearInterval(intervalId); clearInterval(messageIntervalId);
                loadingElement.innerHTML = `<p>오류: ${resultData.message}</p>`;
                setLoadingState(false);
            }
            chatBox.scrollTop = chatBox.scrollHeight;
        } catch (error) {
            console.error('Polling loop error:', error);
        }
    }, pollInterval);
}

// --- 6. 헬퍼 함수 ---
function addMessageToBox(role, content) {
    const rowElement = document.createElement('div');
    rowElement.classList.add('message-row', role);

    if (role === 'assistant') {
        const iconImg = document.createElement('img');
        iconImg.src = "/static/bot-icon.png";
        iconImg.className = "bot-profile-icon";
        iconImg.alt = "bot";
        rowElement.appendChild(iconImg);
    }

    const messageBubble = document.createElement('div');
    messageBubble.setAttribute('role', 'status');
    messageBubble.setAttribute('aria-live', 'polite');

    if (role === 'user') {
        messageBubble.classList.add('user-message');
    } else {
        messageBubble.classList.add('message', role);
    }

    if (content.includes('<div') || content.includes('<p>') || content.includes('<hr>')) {
        messageBubble.innerHTML = content;
    } else {
        const p = document.createElement('p');
        p.textContent = content;
        messageBubble.appendChild(p);
    }

    rowElement.appendChild(messageBubble);
    chatBox.appendChild(rowElement);

    translateCardButtons(messageBubble);

    chatBox.scrollTop = chatBox.scrollHeight;
    return messageBubble;
}

function updateChatHistory(role, content) {
    chatHistory.push({ "role": role, "content": content });
    if (chatHistory.length > MAX_HISTORY_TURNS * 2) chatHistory.shift();
}

function createButtons(optionsArray) {
    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'button-container';
    optionsArray.forEach(optionText => {
        const button = document.createElement('button');
        button.className = 'clarify-btn';
        button.innerText = optionText;
        buttonContainer.appendChild(button);
    });
    chatBox.appendChild(buttonContainer);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function clearButtons() {
    const existingContainer = document.querySelector('.button-container');
    if (existingContainer) existingContainer.remove();
}

// [★수정] 피드백 버튼 추가 함수 (다국어 지원)
function addFeedbackButtons(messageElement, jobId, question, answer) {
    const lang = window.currentLang || 'ko';
    const textData = UI_TEXT[lang].feedback; // 해당 언어의 피드백 텍스트 가져오기

    const feedbackContainer = document.createElement('div');
    feedbackContainer.className = 'feedback-container';

    const feedbackMsg = document.createElement('p');
    feedbackMsg.textContent = textData.question; // "답변이 도움이 되었나요?" (번역됨)
    feedbackContainer.appendChild(feedbackMsg);

    const btnGroup = document.createElement('div');
    btnGroup.className = 'feedback-btn-group';

    const goodBtn = document.createElement('button');
    goodBtn.className = 'feedback-btn';
    goodBtn.textContent = '👍';
    goodBtn.onclick = () => submitFeedback(jobId, question, answer, '👍', feedbackContainer, "");
    btnGroup.appendChild(goodBtn);

    const badBtn = document.createElement('button');
    badBtn.className = 'feedback-btn';
    badBtn.textContent = '👎';
    badBtn.onclick = () => showFeedbackInput(feedbackContainer, jobId, question, answer, '👎');
    btnGroup.appendChild(badBtn);

    feedbackContainer.appendChild(btnGroup);
    messageElement.appendChild(feedbackContainer);
}

// [★수정] 피드백 입력창 (다국어 지원)
function showFeedbackInput(container, jobId, question, answer, feedbackType) {
    const lang = window.currentLang || 'ko';
    const textData = UI_TEXT[lang].feedback;

    container.innerHTML = '';
    const reasonContainer = document.createElement('div');
    reasonContainer.className = 'reason-container';

    // 이유 태그도 번역된 걸로 표시
    const reasons = textData.reasons;

    reasons.forEach(reasonText => {
        const chip = document.createElement('button');
        chip.textContent = reasonText;
        chip.className = 'reason-chip';

        chip.onclick = () => {
            Array.from(reasonContainer.children).forEach(c => c.classList.remove('selected'));
            chip.classList.add('selected');
            if (!container.querySelector('.feedback-input-wrapper')) {
                showCommentInput(container, jobId, question, answer, feedbackType, reasonText);
            } else {
                const existingInput = container.querySelector('.feedback-input-wrapper');
                if (existingInput) existingInput.remove();
                showCommentInput(container, jobId, question, answer, feedbackType, reasonText);
            }
        };
        reasonContainer.appendChild(chip);
    });
    container.appendChild(reasonContainer);
}

// [★수정] 코멘트 입력창 (다국어 지원)
function showCommentInput(container, jobId, question, answer, feedbackType, selectedReason) {
    const lang = window.currentLang || 'ko';
    const textData = UI_TEXT[lang].feedback;

    const inputWrapper = document.createElement('div');
    inputWrapper.className = 'feedback-input-wrapper';

    const input = document.createElement('input');
    input.type = "text";
    input.className = 'feedback-input';
    input.placeholder = textData.input_placeholder; // "자세한 상황을..." (번역됨)
    input.maxLength = 1000;

    const sendBtn = document.createElement('button');
    sendBtn.textContent = textData.send; // "전송" (번역됨)
    sendBtn.className = 'feedback-send-btn';

    sendBtn.onclick = () => {
        const historyStr = JSON.stringify(chatHistory.slice(-4));
        submitFeedback(jobId, question, answer, feedbackType, container, input.value.trim(), selectedReason, historyStr);
    };

    inputWrapper.appendChild(input);
    inputWrapper.appendChild(sendBtn);
    container.appendChild(inputWrapper);

    setTimeout(() => input.focus(), 100);
}

// [★수정] 전송 결과 메시지 (다국어 지원)
async function submitFeedback(jobId, question, answer, feedbackType, containerElement, comment, reason = "", historyStr = "") {
    const lang = window.currentLang || 'ko';
    const textData = UI_TEXT[lang].feedback;

    containerElement.innerHTML = `<p class="feedback-sending">${textData.sending}</p>`;

    try {
        await fetch('/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: jobId,
                question: question,
                answer: answer,
                feedback: feedbackType,
                comment: comment,
                reason: reason,
                chat_history: historyStr
            })
        });

        const thanksText = feedbackType === '👍' ? textData.thanks_good : textData.thanks_bad;
        containerElement.innerHTML = `<p class="feedback-success">${thanksText}</p>`;
    } catch (error) {
        containerElement.innerHTML = `<p style="color:red; font-size:12px;">Error</p>`;
    }
}

function setLoadingState(isLoading) {
    const lang = window.currentLang || 'ko';
    const baseText = UI_TEXT[lang].loading;

    if (isLoading) {
        userInput.disabled = true;
        sendBtn.disabled = true;
        if (micBtn) micBtn.disabled = true;
        userInput.blur();

        userInput.placeholder = baseText;
        let dotCount = 0;

        if (placeholderIntervalId) clearInterval(placeholderIntervalId);
        placeholderIntervalId = setInterval(() => {
            dotCount = (dotCount + 1) % 4;
            const dots = ".".repeat(dotCount);
            userInput.placeholder = `${baseText}${dots}`;
        }, 500);

        if (safetyTimeoutId) clearTimeout(safetyTimeoutId);
        safetyTimeoutId = setTimeout(() => {
            console.warn("Response timeout: Force unlocking input.");
            setLoadingState(false);
            userInput.placeholder = "Timeout. Please try again.";
        }, 45000);

    } else {
        userInput.disabled = false;
        sendBtn.disabled = false;
        if (micBtn) micBtn.disabled = false;

        if (placeholderIntervalId) clearInterval(placeholderIntervalId);
        if (safetyTimeoutId) clearTimeout(safetyTimeoutId);
        placeholderIntervalId = null;
        safetyTimeoutId = null;

        const placeholders = {
            ko: "무엇이 궁금하신가요?",
            en: "What are you looking for?",
            vi: "Bạn đang tìm gì?",
            zh: "您想了解什么？"
        };
        userInput.placeholder = placeholders[lang];
    }
}

// --- 7. 음성 인식 로직 ---
let recognition;
if (canUseMic) {
    recognition = new SpeechRecognition();
    recognition.lang = 'ko-KR';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    micBtn.addEventListener('click', () => { if (micBtn.classList.contains('listening')) recognition.stop(); else recognition.start(); });
    recognition.addEventListener('start', () => { micBtn.classList.add('listening'); userInput.placeholder = "Listening..."; });
    recognition.addEventListener('end', () => { micBtn.classList.remove('listening'); userInput.placeholder = "Ready"; });
    recognition.addEventListener('result', (event) => { userInput.value = event.results[0][0].transcript; toggleInputButtons(); });
    recognition.addEventListener('error', (event) => {
        micBtn.classList.remove('listening');
        userInput.placeholder = "Error";
        setTimeout(() => { userInput.placeholder = "Ready"; }, 2000);
    });
} else {
    if (micBtn) micBtn.style.display = 'none';
    if (sendBtn) sendBtn.style.display = 'flex';
}

window.visualViewport.addEventListener('resize', () => {
    setTimeout(() => {
        chatBox.scrollTop = chatBox.scrollHeight;
    }, 100);
});

function sendSuggestion(text) {
    const userInput = document.getElementById('user-input');
    userInput.value = text;
    toggleInputButtons();
    setTimeout(() => {
        document.getElementById('send-btn').click();
    }, 300);
}

const toggleBtn = document.getElementById('suggestion-toggle-btn');
const suggestionContainer = document.querySelector('.suggestion-container');

function syncSuggestionOverlay() {
    if (!chatBox || !suggestionContainer) return;

    const isVisible = !suggestionContainer.classList.contains('hidden');
    chatBox.classList.toggle('suggestions-visible', isVisible);

    // 추천 질문 바가 열려 있을 때 마지막 답변이 가려지지 않도록
    // 스크롤 위치를 새 하단 여백까지 맞춥니다.
    if (isVisible) {
        requestAnimationFrame(() => {
            chatBox.scrollTop = chatBox.scrollHeight;
        });
    }
}

if (toggleBtn && suggestionContainer) {
    toggleBtn.addEventListener('click', () => {
        suggestionContainer.classList.toggle('hidden');
        toggleBtn.classList.toggle('active');
        syncSuggestionOverlay();
    });
}

window.addEventListener('load', syncSuggestionOverlay);

function showToast(message) {
    const toast = document.getElementById("toast-container");
    toast.textContent = message;
    toast.className = "show";
    setTimeout(() => {
        toast.className = toast.className.replace("show", "");
    }, 3000);
}

window.addEventListener('offline', () => {
    showToast("Offline 🔌");
    userInput.disabled = true;
    userInput.placeholder = "Check connection";
});

window.addEventListener('online', () => {
    showToast("Online! 🚀");
    userInput.disabled = false;
    userInput.placeholder = "Ready";
});

document.addEventListener('DOMContentLoaded', () => {
    const scrollBtn = document.getElementById('scroll-bottom-btn');
    const chatBoxEl = document.getElementById('chat-box');

    if (scrollBtn && chatBoxEl) {
        // 스크롤 버튼 표시 조건 체크 함수
        const checkScrollButton = () => {
            // [핵심 1] 스크롤이 가능한지 (내용이 화면보다 많은지) 확인
            const isScrollable = chatBoxEl.scrollHeight > chatBoxEl.clientHeight + 50;

            // [핵심 2] 사용자가 위로 스크롤했는지 확인 (하단에서 200px 이상 떨어졌는지)
            const isScrolledUp = chatBoxEl.scrollTop + chatBoxEl.clientHeight < chatBoxEl.scrollHeight - 200;

            // 두 조건 모두 만족해야 버튼 표시
            if (isScrollable && isScrolledUp) {
                scrollBtn.classList.add('show');
            } else {
                scrollBtn.classList.remove('show');
            }
        };

        // 스크롤 이벤트 리스너
        chatBoxEl.addEventListener('scroll', checkScrollButton);

        // 클릭 시 맨 아래로 이동
        scrollBtn.addEventListener('click', () => {
            chatBoxEl.scrollTo({
                top: chatBoxEl.scrollHeight,
                behavior: 'smooth'
            });
        });

        // 초기 체크 (페이지 로드 시)
        checkScrollButton();
    }
});

function translateCardButtons(container) {
    const lang = window.currentLang || 'ko';
    if (lang === 'ko') return;

    const dict = {
        en: { detail: "View Details", share: "Share" },
        vi: { detail: "Xem chi tiết", share: "Chia sẻ" },
        zh: { detail: "查看详情", share: "分享" }
    };

    const detailLinks = container.querySelectorAll('.detail-link');
    const shareBtns = container.querySelectorAll('.card-share-btn');

    detailLinks.forEach(el => {
        el.innerText = dict[lang].detail;
    });

    shareBtns.forEach(el => {
        el.innerText = dict[lang].share;
    });
}
// --- [UI Improvements] Toast & Suggestions ---

// 1. Toast Notification Function
function showToast(message) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    
    // Trigger reflow for animation
    void toast.offsetWidth; 
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 2000);
}

// 2. Suggestion Chip Scroll Fix (Prevent click jumping)
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('suggestion-chip')) {
        e.preventDefault(); // Prevent default focus jump
        // Original onclick handler in createButtons/HTML will still fire
    }
});
