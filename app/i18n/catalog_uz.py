"""Uzbek (Latin) message catalog.

Keys are flat ``group.name`` strings and must stay identical across catalogs
(a unit test enforces parity).  Values may contain ``{placeholders}``.
"""

CATALOG: dict[str, str] = {
    # ------------------------------------------------------------- common
    "event.name": "FOODERA EXPO 2026",
    "event.dates": "📅 20–22 oktabr 2026",
    "event.location": "📍 SOF EXPO, Samarqand",
    # ---------------------------------------------------------- language
    "lang.choose": "🌐 Davom etish uchun tilni tanlang:",
    "lang.uz": "🇺🇿 O‘zbekcha",
    "lang.ru": "🇷🇺 Русский",
    # ------------------------------------------------------------- welcome
    "welcome.text": (
        "👋 Assalomu alaykum!\n\n"
        "FOODERA EXPO 2026 — oziq-ovqat sanoati vakillari uchun B2B ko‘rgazma.\n\n"
        "📅 20–22 oktabr 2026\n"
        "📍 SOF EXPO, Samarqand\n\n"
        "Bir necha qisqa savol orqali kompaniyangiz uchun ko‘rgazmada ishtirok "
        "etish imkoniyatini aniqlaymiz."
    ),
    "welcome.cta": "Boshlash →",
    "progress": "Savol {step}/{total}",
    # ------------------------------------------------------- questions
    "q.intent": "FOODERA EXPO sizni qaysi maqsadda qiziqtiryapti?",
    "q.company_type": "Kompaniyangiz qaysi turga kiradi?",
    "q.category": "Biznesingizga mos yo‘nalishni tanlang:",
    "q.company_name": "Kompaniya yoki brend nomini yozing:",
    "q.region": "Kompaniyangiz qayerda joylashgan?",
    "q.country": "Mamlakatingizni yozing:",
    "q.online": "Kompaniyangizning sayt yoki Instagram sahifasi bormi?",
    "q.url": "Sayt va Instagram havolangizni yuboring (yoki @username):",
    "q.contact": "Ism va lavozimingizni yozing.",
    "q.phone": "Bog‘lanish uchun telefon raqamingizni yuboring.",
    "q.stand": "Qaysi format sizga ko‘proq mos?",
    "q.readiness": "Ishtirok bo‘yicha hozirgi holatingiz?",
    "q.v_name": "Ismingizni yozing:",
    "q.v_phone": "Bog‘lanish uchun telefon raqamingizni yuboring.",
    "q.v_region": "Qayerdansiz?",
    "q.v_relation": "Oziq-ovqat sanoati bilan aloqangiz qanday?",
    # -------------------------------------------------------------- hints
    "hint.company_name": "2 tadan 120 tagacha belgi.",
    "hint.contact": "Namuna: Azizbek — Savdo direktori",
    "hint.url": "Masalan: foodcompany.uz yoki @foodcompany",
    "hint.phone": "Xalqaro format ham qabul qilinadi.",
    "hint.optional": "Ixtiyoriy — o‘tkazib yuborishingiz mumkin.",
    "hint.country": "Masalan: Qozog‘iston",
    "hint.category": "Asosiy yo‘nalishni bittasini tanlang.",
    # ------------------------------------------------------------ buttons
    "btn.start": "Boshlash →",
    "btn.back": "⬅️ Orqaga",
    "btn.skip": "O‘tkazish",
    "btn.send_contact": "📱 Telefon raqamni yuborish",
    "btn.manual_phone": "⌨️ Raqamni yozib kiritish",
    "btn.update": "Ma’lumotlarni yangilash",
    "btn.continue": "▶️ Davom etish",
    "btn.restart": "🔄 Boshidan boshlash",
    "btn.cancel": "Bekor qilish",
    "btn.support": "❓ Yordam so‘rash",
    "btn.more_categories": "Davomi ›",
    "btn.fewer_categories": "‹ Ortga",
    "btn.status.contacted": "📞 Aloqaga chiqildi",
    "btn.status.negotiation": "💬 Muzokarada",
    "btn.status.booked": "✅ Stend bron qilindi",
    "btn.status.not_qualified": "❌ Mos emas",
    # ------------------------------------------------------- info/errors
    "err.invalid_option": "Bu variant endi mavjud emas. Iltimos, qaytadan tanlang.",
    "err.stale_callback": "Bu tugma eskirgan. Amaldagi savolga javob bering.",
    "err.no_active_form": "Aktiv so‘rovnoma yo‘q.",
    "err.too_short": "Kamida {min} ta belgi yozing.",
    "err.url_format": "Havola yoki @username formatini tekshiring. Masalan: foodcompany.uz",
    "err.company_name_len": "Kompaniya nomi 2 tadan 120 tagacha belgidan iborat bo‘lishi kerak.",
    "err.contact_len": "Ismni to‘liq yozing (kamida 2 ta belgi).",
    "err.country_len": "Mamlaka nomini to‘liq yozing (kamida 2 ta belgi).",
    "err.phone_format": "Telefon raqami noto‘g‘ri. Namuna: +998 90 123 45 67",
    "err.db": "Kechirasiz, vaqtincha texnik xatolik. Birozdan so‘ng qayta urinib ko‘ring.",
    "err.rate_limited": "Juda faol siz. 😊 Biroz tanaffus qilib, keyin davom etamiz.",
    "err.unknown": "Kechirasiz, xatolik yuz berdi. Iltimos, /start orqali qaytadan urinib ko‘ring.",
    "err.lead_not_found": "Bu lead topilmadi.",
    "err.status_changed": "Bu leadning holatini boshqa menejer yangilab yubordi. Kartani qaytadan ko‘ring.",
    "err.status_same": "Bu lead allaqachon shu holatda.",
    "err.status_transition": "Bunday holat o‘zgarishiga ruxsat yo‘q.",
    "err.not_manager": "Bu amalni faqat sotuv guruhi a‘zolari bajara oladi.",
    "err.admin_only": "Bu buyruq faqat administratorlar uchun.",
    "info.already_applied": (
        "Sizning murojaatingiz avval qabul qilingan.\n\n"
        "Agar ma’lumotlarni yangilamoqchi bo‘lsangiz:"
    ),
    "info.draft_found": "Tugallanmagan so‘rovnomangiz bor. Davom etasizmi yoki boshdan boshlaymizmi?",
    "info.cancelled": "So‘rovnoma bekor qilindi.\nQaytadan boshlash uchun /start.",
    "info.lead_code": "Murojaat raqamingiz: {code}",
    "info.restarted": "Yangi so‘rovnoma boshlandi.",
    "info.lang_saved": "Til sozlandi ✅",
    "info.no_leads": "Hozircha leadlar yo‘q.",
    "info.current": "Javobingiz: {value}",
    "info.field_required": "Bu javobni kiritish kerak.",
    "info.first_question": "Bu birinchi savol.",
    "err.use_buttons": "Iltimos, tugmalardan birini tanlang yoki /start orqali qaytadan boshlang.",
    "err.phone_foreign": "Iltimos, o‘zingizning raqamingizni yuboring.",
    "visitor.intro": "Tushunarli! Ko‘rgazmaga tashrif buyurish uchun 3 ta qisqa savolga javob bering.",
    "flow.visitor_intro": "👋 Sizga ko‘rgazmaga tashrif buyurish bo‘yicha bir necha savol beramiz.",
    "help.text": (
        "🤖 Ushbu bot FOODERA EXPO 2026 ishtirokchi arizalarini qabul qiladi.\n\n"
        "/start — so‘rovnomani boshlash\n"
        "/restart — boshidan boshlash\n"
        "/help — yordam"
    ),
    # --------------------------------------------------------- completion
    "success.qualified": (
        "✅ Rahmat! Ma’lumotlaringiz qabul qilindi.\n\n"
        "FOODERA EXPO menejeri siz bilan bog‘lanib, mavjud stendlar, joylashuv va "
        "ishtirok shartlari bo‘yicha ma’lumot beradi.\n\n"
        "📅 20–22 oktabr 2026\n📍 SOF EXPO, Samarqand"
    ),
    "success.warm": (
        "✅ Rahmat! Kompaniyangiz haqidagi ma’lumotlarni qabul qildik.\n\n"
        "FOODERA EXPO ishtirok imkoniyatlari bo‘yicha menejerimiz siz bilan bog‘lanadi.\n\n"
        "📅 20–22 oktabr 2026\n📍 SOF EXPO, Samarqand"
    ),
    "success.cold": (
        "Rahmat! Murojaatingiz qabul qilindi.\n\n"
        "FOODERA EXPO jamoasi ma’lumotlaringizni ko‘rib chiqadi.\n\n"
        "📅 20–22 oktabr 2026\n📍 SOF EXPO, Samarqand"
    ),
    "success.visitor": (
        "✅ Rahmat!\n\n"
        "FOODERA EXPO mehmon sifatida tashrif buyurish bo‘yicha ma’lumotlaringiz "
        "qabul qilindi.\n\n"
        "📅 20–22 oktabr 2026\n📍 SOF EXPO, Samarqand"
    ),
    "support.line": "Savollar bo‘lsa: {username}",
    # ---------------------------------------------------------- lead card
    "card.title_lead": "🔥 FOODERA — YANGI LEAD",
    "card.title_visitor": "👤 FOODERA — MEHMON RO‘YXATGA OLINDI",
    "card.high_intent": "🔥 HIGH INTENT",
    "card.status": "Status",
    "card.score": "Score",
    "card.company": "🏢 Kompaniya",
    "card.contact": "👤 Kontakt",
    "card.phone": "📱 Telefon",
    "card.region": "📍 Hudud",
    "card.company_type": "🏭 Kompaniya turi",
    "card.category": "🍴 Yo‘nalish",
    "card.stand": "📐 Stend",
    "card.readiness": "🎯 Holati",
    "card.instagram": "🌐 Instagram",
    "card.website": "🌐 Sayt",
    "card.source": "📢 Manba",
    "card.creative": "🎨 Kreativ",
    "card.campaign": "📣 Kampaniya",
    "card.telegram": "Telegram",
    "card.user_id": "🆔 User ID",
    "card.lead_id": "🔖 Lead ID",
    "card.sent_at": "⏱ Yuborilgan",
    "card.relation": "🤝 Sanoat bilan aloqa",
    "card.country": "🌍 Mamlakat",
    "card.status_line": "📌 Holat: {status}",
    "card.status_meta": "📌 Holat: {status} · {manager} · {time}",
    "card.value_none": "—",
    "cls.HOT": "🔥 HOT",
    "cls.WARM": "🌤 WARM",
    "cls.COLD": "❄️ COLD",
    "cls.LOW": "⚪ LOW",
    "cls.VISITOR": "👤 VISITOR",
    "status.NEW": "🆕 NEW",
    "status.CONTACTED": "📞 CONTACTED",
    "status.NEGOTIATION": "💬 NEGOTIATION",
    "status.BOOKED": "✅ BOOKED",
    "status.NOT_QUALIFIED": "❌ NOT_QUALIFIED",
    "status.CLOSED": "📁 CLOSED",
    # ------------------------------------------------------------ options
    "opt.intent.stand": "Kompaniyamiz bilan stendda qatnashmoqchimiz",
    "opt.intent.pricing": "Stendlar va narxlar haqida ma’lumot olmoqchimiz",
    "opt.intent.partner": "Hamkorlik qilishni xohlaymiz",
    "opt.intent.visitor": "Mehmon sifatida tashrif buyurmoqchiman",
    "opt.company_type.manufacturer": "Ishlab chiqaruvchi",
    "opt.company_type.distributor": "Distribyutor",
    "opt.company_type.importer": "Importyor / Eksportyor",
    "opt.company_type.retail": "Retail / savdo tarmog‘i",
    "opt.company_type.horeca": "HoReCa",
    "opt.company_type.ingredient": "Ingredient / xomashyo yetkazib beruvchi",
    "opt.company_type.equipment": "Uskuna / texnologiya kompaniyasi",
    "opt.company_type.logistics": "Logistika kompaniyasi",
    "opt.company_type.other": "Boshqa",
    "opt.category.non_alcoholic_drinks": "Alkogolsiz ichimliklar",
    "opt.category.grocery": "Bakaleya",
    "opt.category.frozen_and_semi_finished": "Muzlatilgan va yarim tayyor mahsulotlar",
    "opt.category.confectionery_and_bakery": "Qandolat va non-bulka mahsulotlari",
    "opt.category.canned_food": "Konserva mahsulotlari",
    "opt.category.oils_and_sauces": "Yog‘-moy mahsulotlari va souslar",
    "opt.category.dairy_and_cheese": "Sut mahsulotlari va pishloqlar",
    "opt.category.meat_poultry_eggs": "Go‘sht, parranda va tuxum",
    "opt.category.organic_and_healthy": "Organik va healthy food",
    "opt.category.fish_and_seafood": "Baliq va dengiz mahsulotlari",
    "opt.category.tea_and_coffee": "Choy va qahva",
    "opt.category.ingredients_and_components": "Ingredientlar va komponentlar",
    "opt.category.produce_and_dried_fruits": "Meva-sabzavot / quruq meva",
    "opt.category.equipment_and_technologies": "Uskuna va texnologiyalar",
    "opt.category.logistics": "Logistika",
    "opt.category.other": "Boshqa",
    "opt.region.tashkent": "Toshkent",
    "opt.region.samarkand": "Samarqand",
    "opt.region.andijan": "Andijon",
    "opt.region.fergana": "Farg‘ona",
    "opt.region.namangan": "Namangan",
    "opt.region.bukhara": "Buxoro",
    "opt.region.qashqadaryo": "Qashqadaryo",
    "opt.region.surkhandaryo": "Surxondaryo",
    "opt.region.khorezm": "Xorazm",
    "opt.region.jizzakh": "Jizzax",
    "opt.region.syrdarya": "Sirdaryo",
    "opt.region.navoiy": "Navoiy",
    "opt.region.karakalpakstan": "Qoraqalpog‘iston",
    "opt.region.other_region": "Boshqa hudud",
    "opt.region.foreign": "O‘zbekistondan tashqarida",
    "opt.online.instagram": "Instagram bor",
    "opt.online.website": "Sayt bor",
    "opt.online.both": "Ikkalasi ham bor",
    "opt.online.none": "Yo‘q",
    "opt.stand.size_9": "9 m²",
    "opt.stand.size_18": "18 m²",
    "opt.stand.size_27": "27 m²",
    "opt.stand.size_36_plus": "36 m² yoki undan katta",
    "opt.stand.undecided": "Hali aniqlamadik",
    "opt.readiness.ready_to_book": "Stend bron qilishga tayyormiz",
    "opt.readiness.review_options": "Variant va narxlarni ko‘rib chiqamiz",
    "opt.readiness.manager_call": "Avval menejer bilan gaplashmoqchimiz",
    "opt.readiness.just_interesting": "Hozircha faqat qiziqyapmiz",
    "opt.relation.professional": "Oziq-ovqat sanoati mutaxassisi",
    "opt.relation.retail": "Retail / savdo",
    "opt.relation.horeca": "HoReCa",
    "opt.relation.distributor": "Distribyutor",
    "opt.relation.student": "Talaba",
    "opt.relation.other": "Boshqa",
    "opt.field.website": "Sayt",
    "opt.field.instagram": "Instagram",
}
