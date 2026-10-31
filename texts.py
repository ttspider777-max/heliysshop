import html as _html

import config
import db

# Единый стиль экранов: жирный заголовок, под ним — карточка-цитата (<blockquote>), потом действия.
DIVIDER = "━━━━━━━━━━━━━━"
D = DIVIDER

SHOP = _html.escape(config.SHOP_NAME)
TITLE = _html.escape(config.SHOP_TITLE)
if config.CHILD:  # у бота клиента — нейтральное описание, владелец поменяет его в ✏️ Оформление
    TAGLINE = ("Цифровые товары — быстро и удобно.", "Digital goods — fast and easy.")
else:
    TAGLINE = ("Физические номера и AI‑сервисы — быстро и удобно.", "Physical numbers and AI services — fast and easy.")


def _card(title, body):
    """Заголовок + карточка-цитата."""
    return f"<b>{title}</b>\n<blockquote>{body}</blockquote>"


# Тексты интерфейса: ключ -> (русский, английский).
# Любой текст админ может переопределить в админ-панели (✏️ Оформление → 📝 Все тексты), с премиум-эмодзи.
# Переопределённые тексты хранятся в базе и при обновлении кода не сбрасываются.
TEXTS = {
    # В приветствии: {name} — имя, {balance} — баланс, {orders} — заказов, {status} — статус покупателя.
    "welcome": (
        "✨ <b>" + TITLE + "</b>\n" + TAGLINE[0] + "\n\n"
        "<blockquote>👋 Привет, <b>{name}</b>!\n💰 Баланс: <b>{balance}</b>\n🏅 Статус: <b>{status}</b></blockquote>\n"
        "⚡ Автовыдача 24/7  ·  💬 Поддержка прямо в боте\n\n👇 Открывай магазин",
        "✨ <b>" + TITLE + "</b>\n" + TAGLINE[1] + "\n\n"
        "<blockquote>👋 Hi, <b>{name}</b>!\n💰 Balance: <b>{balance}</b>\n🏅 Status: <b>{status}</b></blockquote>\n"
        "⚡ Instant delivery 24/7  ·  💬 Support right in the bot\n\n👇 Open the shop",
    ),
    "shop_soon": (
        "🛍 Магазин открывается в мини-приложении. Администратор ещё не подключил его адрес — пока покажу каталог здесь.",
        "🛍 The shop opens as a mini app. The admin hasn't set its address yet — showing the catalog here for now.",
    ),
    "catalog_title": ("🛍 <b>Каталог " + SHOP + "</b>", "🛍 <b>" + SHOP + " catalog</b>"),
    "catalog_body": (
        "<blockquote>🔥 <b>Хиты</b> — по реальным покупкам\n🏷 <b>Скидки</b> — активные предложения\n"
        "🔎 <b>Поиск</b> — по названию и описанию</blockquote>",
        "<blockquote>🔥 <b>Hits</b> — based on real purchases\n🏷 <b>Sale</b> — active offers\n"
        "🔎 <b>Search</b> — by name and description</blockquote>",
    ),
    "list_cat": ("<b>{name}</b>\nВыберите товар 👇", "<b>{name}</b>\nChoose a product 👇"),
    "list_hits": ("🔥 <b>Хиты</b>\nСамые покупаемые прямо сейчас 👇", "🔥 <b>Hits</b>\nBest-sellers right now 👇"),
    "list_disc": ("🏷 <b>Скидки</b>\nТолько активные предложения 👇", "🏷 <b>Sale</b>\nActive offers only 👇"),
    "list_new": ("🆕 <b>Новинки</b>\nНедавно добавленные товары 👇", "🆕 <b>New</b>\nRecently added 👇"),
    "list_recent": ("🕓 <b>Недавно</b>\nТовары, которые вы смотрели 👇", "🕓 <b>Recent</b>\nProducts you viewed 👇"),
    "list_fav": ("❤️ <b>Избранное</b>", "❤️ <b>Favorites</b>"),
    "list_srch": ("🔎 <b>Поиск:</b> {q}", "🔎 <b>Search:</b> {q}"),
    "list_empty": ("\n\n<i>Здесь пока пусто 🤷</i>", "\n\n<i>Nothing here yet 🤷</i>"),
    "search_prompt": ("🔎 Введите название или часть описания товара:", "🔎 Enter a product name or part of its description:"),
    "price": ("💰 Цена: <b>{price}</b>", "💰 Price: <b>{price}</b>"),
    "price_disc": ("💰 Цена: <s>{old}</s> <b>{price}</b>  (−{pct}%)", "💰 Price: <s>{old}</s> <b>{price}</b>  (−{pct}%)"),
    "promo_applied": ("🎟 С промокодом <code>{code}</code>: <b>{price}</b>", "🎟 With promo <code>{code}</code>: <b>{price}</b>"),
    "stock": ("📦 В наличии: <b>{n}</b> шт.", "📦 In stock: <b>{n}</b> pcs."),
    "multi_hint": ("🔢 Можно купить сразу несколько штук", "🔢 You can buy several at once"),
    "stock_manual": ("📦 В наличии", "📦 In stock"),
    "stock_out": ("🔴 <b>Нет в наличии</b>", "🔴 <b>Out of stock</b>"),
    "out_short": ("нет в наличии", "out of stock"),
    "per_item": (" / шт.", " / pc."),
    "min_hint": ("🔢 Покупка по количеству — от <b>{min}</b> шт.", "🔢 Sold by quantity — from <b>{min}</b> pcs."),
    "qty_low": ("Минимальное количество — {min} шт.", "Minimum quantity is {min} pcs."),
    "stars_off": ("⭐ Этот товар нельзя оплатить звёздами", "⭐ This product can't be paid with Stars"),
    "not_found": ("Товар не найден", "Product not found"),
    "out_alert": ("❌ Товара нет в наличии. Нажмите «Уведомить о поступлении».", "❌ Out of stock. Tap «Notify me»."),
    "choose_pay": (
        _card("🧾 Оформление заказа", "📦 {name}\n💰 К оплате: <b>{price}</b>\n💳 Ваш баланс: {balance}") +
        "\nВыберите способ оплаты 👇",
        _card("🧾 Checkout", "📦 {name}\n💰 To pay: <b>{price}</b>\n💳 Your balance: {balance}") +
        "\nChoose a payment method 👇",
    ),
    "no_money": ("❌ Недостаточно средств на балансе", "❌ Insufficient balance"),
    "paid_balance": ("✅ Заказ #{oid} оплачен с баланса. Товар отправлен ниже 👇", "✅ Order #{oid} paid from balance. Product sent below 👇"),
    "sbp_text": (
        _card("💳 Оплата по СБП", "🧾 Заказ #{oid}\n📦 {name}\n💰 Сумма: <b>{price}</b>") +
        "\n📲 <b>Реквизиты:</b>\n{details}\n\nПереведите <b>точную сумму</b> и нажмите «Я оплатил».",
        _card("💳 SBP payment", "🧾 Order #{oid}\n📦 {name}\n💰 Amount: <b>{price}</b>") +
        "\n📲 <b>Details:</b>\n{details}\n\nTransfer the <b>exact amount</b> and tap «I have paid».",
    ),
    "send_receipt": ("📸 Отправьте скриншот или файл чека об оплате одним сообщением.", "📸 Send a screenshot or file of the payment receipt."),
    "need_receipt": ("Пожалуйста, отправьте фото или файл чека 📸", "Please send a photo or file of the receipt 📸"),
    "receipt_sent": (
        "✅ Чек отправлен администратору.\nПосле проверки товар придёт автоматически.",
        "✅ Receipt sent to the administrator.\nThe product will be delivered automatically after review.",
    ),
    "order_bad": ("Заказ недоступен", "Order unavailable"),
    "order_canceled": ("🚫 Заказ отменён.", "🚫 Order canceled."),
    "order_rejected": ("❌ К сожалению, вашу заявку отклонили.\n🧾 Заказ #{oid}", "❌ Unfortunately, your request was rejected.\n🧾 Order #{oid}"),
    "order_delivered": (
        _card("✅ Заказ #{oid} выполнен!", "📦 {name}") + "\n🔑 <b>Ваши данные:</b>\n<code>{content}</code>\n\nСпасибо за покупку! 💜",
        _card("✅ Order #{oid} completed!", "📦 {name}") + "\n🔑 <b>Your data:</b>\n<code>{content}</code>\n\nThank you! 💜",
    ),
    "order_delivered_file": (
        _card("✅ Заказ #{oid} выполнен!", "📦 {name}") + "\n🔑 Ваши данные — в файле выше.\nСпасибо за покупку! 💜",
        _card("✅ Order #{oid} completed!", "📦 {name}") + "\n🔑 Your data is in the attached file.\nThank you! 💜",
    ),
    "qty_title": (
        _card("🛒 {name}", "💰 Цена за шт.: <b>{price}</b>\n📦 Доступно: {avail}") +
        "\n🔢 Количество: <b>{qty}</b>\n💳 Итого: <b>{total}</b>",
        _card("🛒 {name}", "💰 Price per item: <b>{price}</b>\n📦 Available: {avail}") +
        "\n🔢 Quantity: <b>{qty}</b>\n💳 Total: <b>{total}</b>",
    ),
    "qty_avail_manual": ("в любом количестве", "any amount"),
    "qty_avail_n": ("{n} шт.", "{n} pcs."),
    "qty_prompt": ("✏️ Введите нужное количество (от {min} до {max}):", "✏️ Enter the quantity ({min} to {max}):"),
    "qty_bad": ("❌ Введите число от {min} до {max}", "❌ Enter a number from {min} to {max}"),
    "qty_max": ("Максимум — {max} шт.", "Maximum is {max} pcs."),
    "qty_min": ("Минимум — {min} шт.", "Minimum is {min} pc."),
    "order_manual": (
        "✅ Оплата заказа #{oid} подтверждена!\nАдминистратор выдаст товар в ближайшее время.",
        "✅ Payment for order #{oid} confirmed!\nThe administrator will deliver the product shortly.",
    ),
    "order_refunded": (
        "⚠️ Товар по заказу #{oid} закончился. {price} зачислено на ваш баланс.",
        "⚠️ The product for order #{oid} ran out. {price} was credited to your balance.",
    ),
    "order_refunded_ext": (
        "⚠️ Не удалось выдать товар по заказу #{oid} — поставщик не ответил. {price} зачислено на ваш баланс, "
        "попробуйте ещё раз позже или напишите в поддержку.",
        "⚠️ We couldn't deliver the product for order #{oid} — the supplier did not respond. {price} was credited to your "
        "balance; try again later or contact support.",
    ),
    "notify_on": ("🔔 Мы сообщим, когда товар появится в наличии", "🔔 We'll let you know when it's back in stock"),
    "notify_arrived": ("🔔 <b>Товар снова в наличии!</b>\n\n📦 {name}", "🔔 <b>Back in stock!</b>\n\n📦 {name}"),
    "fav_added": ("❤️ Добавлено в избранное", "❤️ Added to favorites"),
    "fav_removed": ("💔 Удалено из избранного", "💔 Removed from favorites"),
    "orders_title": ("📦 <b>Ваши заказы</b> · {n}", "📦 <b>Your orders</b> · {n}"),
    "orders_empty": ("\n\n<i>У вас пока нет заказов.</i>", "\n\n<i>You have no orders yet.</i>"),
    "order_detail": (
        _card("🧾 Заказ #{oid}", "📦 {name}\n💰 Сумма: {price}\n💳 Оплата: {method}\n📅 {date}\n📍 {status}"),
        _card("🧾 Order #{oid}", "📦 {name}\n💰 Amount: {price}\n💳 Payment: {method}\n📅 {date}\n📍 {status}"),
    ),
    "order_content": ("\n🔑 <b>Данные:</b>\n<code>{content}</code>", "\n🔑 <b>Data:</b>\n<code>{content}</code>"),
    # Профиль: {id} {username} {name} {date} {orders} {balance} {status} {progress} {deposited}
    "profile": (
        "👤 <b>Профиль</b>\n"
        "<blockquote>🆔 ID: <code>{id}</code>\n👤 Ник: {username}\n📅 С нами с {date}</blockquote>\n"
        "💰 Баланс: <b>{balance}</b>\n🏅 Статус: <b>{status}</b>\n{progress}\n🛒 Заказов: <b>{orders}</b>",
        "👤 <b>Profile</b>\n"
        "<blockquote>🆔 ID: <code>{id}</code>\n👤 Username: {username}\n📅 Member since {date}</blockquote>\n"
        "💰 Balance: <b>{balance}</b>\n🏅 Status: <b>{status}</b>\n{progress}\n🛒 Orders: <b>{orders}</b>",
    ),
    "profile_next": ("<code>{bar}</code> {pct}%\n<i>До «{next}» осталось {left}</i>",
                     "<code>{bar}</code> {pct}%\n<i>{left} left to «{next}»</i>"),
    "profile_max": ("<i>👑 Максимальный статус!</i>", "<i>👑 Top status reached!</i>"),
    "profile_promo": ("\n🎟 Активный промокод: <code>{code}</code> (−{pct}%)", "\n🎟 Active promo: <code>{code}</code> (−{pct}%)"),
    "statuses": (
        "🏅 <b>Статусы</b>\nСтатус растёт от суммы пополнений и оплат.\n\n{list}",
        "🏅 <b>Statuses</b>\nYour status grows with top-ups and payments.\n\n{list}",
    ),
    "bonus_ok": ("🎁 +{amount} на баланс! Приходите снова через 24 часа.", "🎁 +{amount} to your balance! Come back in 24 hours."),
    "bonus_wait": ("⏳ Бонус уже получен. Следующий — через {left}.", "⏳ Bonus already claimed. Next one in {left}."),
    "bonus_off": ("Ежедневный бонус сейчас выключен.", "The daily bonus is currently off."),
    # ---------- пополнение баланса ----------
    "topup_title": (
        _card("💳 Пополнение баланса", "💰 Сейчас на балансе: <b>{balance}</b>\n📉 Минимум: {min}") +
        "\nВыберите сумму или введите свою 👇",
        _card("💳 Top up balance", "💰 Current balance: <b>{balance}</b>\n📉 Minimum: {min}") +
        "\nChoose an amount or enter your own 👇",
    ),
    "topup_custom": ("✏️ Введите сумму пополнения в рублях (от {min}):", "✏️ Enter the amount in RUB (from {min}):"),
    "topup_bad": ("❌ Введите число от {min}", "❌ Enter a number from {min}"),
    "topup_method": (
        _card("💳 Пополнение на {amount}", "Выберите способ оплаты 👇"),
        _card("💳 Top up {amount}", "Choose a payment method 👇"),
    ),
    "topup_sbp": (
        _card("💳 Пополнение по СБП", "🧾 Заявка #{tid}\n💰 Сумма: <b>{amount}</b>") +
        "\n📲 <b>Реквизиты:</b>\n{details}\n\nПереведите <b>точную сумму</b> и нажмите «Я оплатил».",
        _card("💳 SBP top-up", "🧾 Request #{tid}\n💰 Amount: <b>{amount}</b>") +
        "\n📲 <b>Details:</b>\n{details}\n\nTransfer the <b>exact amount</b> and tap «I have paid».",
    ),
    "topup_receipt_sent": ("✅ Чек отправлен. После проверки деньги придут на баланс.",
                           "✅ Receipt sent. The money will arrive after review."),
    "topup_done": ("✅ Баланс пополнен на <b>{amount}</b>!\n💰 Теперь на балансе: <b>{balance}</b>",
                   "✅ Balance topped up by <b>{amount}</b>!\n💰 Now: <b>{balance}</b>"),
    "topup_rejected": ("❌ Пополнение #{tid} не подтверждено. Если это ошибка — напишите в поддержку.",
                       "❌ Top-up #{tid} was not confirmed. If this is a mistake, contact support."),
    "topup_stars_desc": ("Пополнение баланса на {amount}", "Balance top-up {amount}"),
    # ---------- поддержка ----------
    "sup_prompt": (
        _card("💬 Поддержка", "Опишите вашу проблему или вопрос одним сообщением.\n"
                              "Можно приложить фото, видео или файл.") + "\nАдминистратор ответит прямо здесь, в боте.",
        _card("💬 Support", "Describe your problem or question in one message.\n"
                            "You can attach a photo, video or file.") + "\nAn administrator will reply right here in the bot.",
    ),
    "sup_sent": ("✅ Обращение #{tid} отправлено. Ответ придёт сюда, в чат с ботом.",
                 "✅ Ticket #{tid} sent. The reply will come here, in the bot chat."),
    "sup_more_sent": ("✅ Сообщение добавлено к обращению #{tid}.", "✅ Message added to ticket #{tid}."),
    "sup_active": (
        _card("💬 Обращение #{tid}", "📍 {status}\n📅 Создано: {date}") + "\nМожно дописать сообщение или закрыть вопрос.",
        _card("💬 Ticket #{tid}", "📍 {status}\n📅 Created: {date}") + "\nYou can add a message or close the ticket.",
    ),
    "sup_more_prompt": ("✍️ Напишите сообщение для поддержки:", "✍️ Write your message to support:"),
    "sup_reply": ("💬 <b>Ответ поддержки</b> · обращение #{tid}", "💬 <b>Support reply</b> · ticket #{tid}"),
    "sup_closed": ("✅ Обращение #{tid} закрыто. Если появятся вопросы — пишите снова!",
                   "✅ Ticket #{tid} closed. If you have more questions — write again!"),
    "sup_rejected": ("🚫 Обращение #{tid} отклонено поддержкой.", "🚫 Ticket #{tid} was declined by support."),
    "sup_status_open": ("⏳ ждёт ответа", "⏳ waiting for reply"),
    "sup_status_answered": ("💬 есть ответ", "💬 answered"),
    "refs": (
        "👥 <b>Реферальная программа</b>\n<blockquote>🔗 <code>{link}</code></blockquote>\n"
        "👤 Приглашено: <b>{invited}</b>\n🛒 Купили: <b>{bought}</b>\n💸 Заработано: <b>{earned}</b>\n"
        "💰 Доступно к выводу: <b>{available}</b>\n\n"
        "<i>Вы получаете {pct}% с каждой покупки приглашённых. Вывод — на баланс бота через заявку, минимум {min}.</i>",
        "👥 <b>Referral program</b>\n<blockquote>🔗 <code>{link}</code></blockquote>\n"
        "👤 Invited: <b>{invited}</b>\n🛒 Bought: <b>{bought}</b>\n💸 Earned: <b>{earned}</b>\n"
        "💰 Available: <b>{available}</b>\n\n"
        "<i>You get {pct}% of every purchase by your referrals. Withdrawal goes to your bot balance, minimum {min}.</i>",
    ),
    "invite_text": ("Заходи в " + config.SHOP_NAME + " 🔥", "Check out " + config.SHOP_NAME + " 🔥"),
    "refreshed": ("🔄 Обновлено", "🔄 Refreshed"),
    "ref_new": ("👥 По вашей ссылке присоединился новый пользователь!", "👥 A new user joined via your link!"),
    "ref_bonus": ("💸 Реферальное начисление: <b>+{amount}</b>", "💸 Referral reward: <b>+{amount}</b>"),
    "wd_min": ("Минимальная сумма вывода — {min}", "Minimum withdrawal is {min}"),
    "wd_sent": ("✅ Заявка на вывод {amount} отправлена администратору", "✅ Withdrawal request for {amount} sent to admin"),
    "wd_ok": ("✅ Заявка на вывод одобрена! {amount} зачислено на баланс бота.", "✅ Withdrawal approved! {amount} credited to your bot balance."),
    "wd_no": ("❌ Заявка на вывод {amount} отклонена. Средства возвращены на реферальный баланс.",
              "❌ Withdrawal of {amount} rejected. Funds returned to referral balance."),
    "promo_prompt": ("🎟 Введите промокод:", "🎟 Enter a promo code:"),
    "promo_ok": ("✅ Промокод <code>{code}</code> активирован!\nСкидка <b>{pct}%</b> применится к следующей покупке.",
                 "✅ Promo code <code>{code}</code> activated!\n<b>{pct}%</b> discount applies to your next purchase."),
    "promo_bad": ("❌ Промокод не найден или закончился.", "❌ Promo code not found or expired."),
    "promo_used": ("❌ Вы уже использовали этот промокод.", "❌ You have already used this promo code."),
    "lang_choose": ("🌐 Выберите язык / Choose language:", "🌐 Выберите язык / Choose language:"),
    "sub_prompt": (
        _card("📢 Подпишитесь, чтобы пользоваться ботом", "Подпишитесь на каналы ниже и нажмите «Проверить подписку»."),
        _card("📢 Subscribe to use the bot", "Subscribe to the channels below and tap «Check subscription»."),
    ),
    "sub_not_yet": ("❌ Вы ещё не подписались на все каналы", "❌ You haven't subscribed to all channels yet"),
    "sub_thanks": ("✅ Спасибо за подписку!", "✅ Thanks for subscribing!"),
    "banned": ("🚫 Вы заблокированы в этом боте.", "🚫 You are banned from this bot."),
    "m_balance": ("Баланс", "Balance"),
    "m_sbp": ("СБП", "SBP"),
    "m_stars": ("Звёзды", "Stars"),
    # документы
    "docs_title": (_card("📄 Документы", "Условия работы магазина:"), _card("📄 Documents", "Terms of service:")),
    "doc_empty": ("Документ пока не опубликован.", "This document is not published yet."),
    "agree_prompt": (
        _card("📜 Прежде чем начать", "Ознакомьтесь с Пользовательским соглашением и Политикой конфиденциальности "
                                     "и нажмите «Принимаю»."),
        _card("📜 Before you start", "Please read the Terms of Service and the Privacy Policy and tap «I agree»."),
    ),
    "pay_terms": ("Оплачивая заказ, вы принимаете условия документов:", "By paying you accept the terms of:"),
    # ---------- «🤖 Создать своего бота» ----------
    # В mb_info можно использовать {price} — цену создания (⚙️ Настройки → 🤖 Цена бота).
    "mb_info": (
        "🤖 <b>Свой бот-магазин</b>\n"
        "<blockquote>Такой же магазин, как этот: своё название, товары, мини-приложение, оплата по СБП и звёздами, "
        "поддержка, рефералы, промокоды и полная админ-панель.</blockquote>\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Нажмите «Я прочитал» и оплатите создание — <b>{price}</b>\n"
        "2️⃣ Нажмите «Я оплатил» и отправьте чек — администратор проверит оплату\n"
        "3️⃣ Создайте бота в @BotFather: /newbot → название → юзернейм (на конце <code>bot</code>)\n"
        "4️⃣ Пришлите сюда токен, который выдаст BotFather\n"
        "5️⃣ Бот сам встанет на хостинг и включится — откройте его и нажмите /admin\n\n"
        "👑 Вы владелец и админ своего бота. Хостинг — на нашем сервере, ничего настраивать не нужно.\n"
        "<i>Администрация сервиса сохраняет технический доступ к боту для поддержки и резервных копий.</i>",
        "🤖 <b>Your own shop bot</b>\n"
        "<blockquote>The same shop as this one: your own name, products, mini app, SBP and Stars payments, "
        "support, referrals, promo codes and a full admin panel.</blockquote>\n"
        "<b>How it works:</b>\n"
        "1️⃣ Tap «I've read it» and pay for setup — <b>{price}</b>\n"
        "2️⃣ Tap «I have paid» and send the receipt — the admin will check the payment\n"
        "3️⃣ Create a bot in @BotFather: /newbot → name → username (ending with <code>bot</code>)\n"
        "4️⃣ Send the token BotFather gives you here\n"
        "5️⃣ The bot is hosted and started automatically — open it and send /admin\n\n"
        "👑 You'll be the owner and admin of your bot. It runs on our server, no setup needed.\n"
        "<i>The service team keeps technical access to the bot for support and backups.</i>",
    ),
    "mb_bots_head": ("\n\n🤖 <b>Ваши боты:</b>", "\n\n🤖 <b>Your bots:</b>"),
    "mb_bot_line": ("\n• {name} — {status}", "\n• {name} — {status}"),
    "mb_send_token": ("\n\n👉 Пришлите токен из @BotFather сообщением в этот чат.",
                      "\n\n👉 Send the token from @BotFather as a message in this chat."),
    "mb_pay": (
        _card("💳 Оплата создания бота", "🧾 Заявка #{bid}\n💰 Сумма: <b>{price}</b>") +
        "\n📲 <b>Реквизиты:</b>\n{details}\n\nПереведите <b>точную сумму</b> и нажмите «Я оплатил».",
        _card("💳 Bot setup payment", "🧾 Request #{bid}\n💰 Amount: <b>{price}</b>") +
        "\n📲 <b>Details:</b>\n{details}\n\nTransfer the <b>exact amount</b> and tap «I have paid».",
    ),
    "mb_receipt_sent": (
        "✅ Чек отправлен администратору.\nПосле проверки я попрошу прислать токен вашего бота.",
        "✅ Receipt sent to the administrator.\nAfter review I'll ask you for your bot's token.",
    ),
    "mb_approved": (
        "✅ <b>Оплата подтверждена!</b>\nПришлите токен от @BotFather. Как его получить:\n\n"
        "<blockquote>1. Откройте @BotFather и отправьте /newbot\n"
        "2. Придумайте название — его увидят покупатели\n"
        "3. Придумайте юзернейм латиницей, на конце <code>bot</code> (например <code>myshop_bot</code>)\n"
        "4. BotFather пришлёт токен вида <code>123456789:AAH…</code> — скопируйте его целиком и отправьте сюда</blockquote>\n"
        "🔒 Никому, кроме этого бота, токен не отправляйте.",
        "✅ <b>Payment confirmed!</b>\nSend the token from @BotFather. How to get it:\n\n"
        "<blockquote>1. Open @BotFather and send /newbot\n"
        "2. Choose a name — customers will see it\n"
        "3. Choose a username in Latin letters ending with <code>bot</code> (e.g. <code>myshop_bot</code>)\n"
        "4. BotFather will send a token like <code>123456789:AAH…</code> — copy all of it and send it here</blockquote>\n"
        "🔒 Don't send the token to anyone except this bot.",
    ),
    "mb_rejected": (
        "❌ Оплата за создание бота (заявка #{bid}) не подтверждена. Если это ошибка — напишите в поддержку.",
        "❌ Payment for bot setup (request #{bid}) was not confirmed. If this is a mistake, contact support.",
    ),
    "mb_checking": ("⏳ Проверяю токен и запускаю бота…", "⏳ Checking the token and starting the bot…"),
    "mb_token_format": (
        "❌ Это не похоже на токен. Он выглядит так: <code>123456789:AAH…</code> — скопируйте его целиком из @BotFather.",
        "❌ That doesn't look like a token. It looks like <code>123456789:AAH…</code> — copy all of it from @BotFather.",
    ),
    "mb_token_invalid": (
        "❌ Telegram не принял этот токен. Проверьте, что скопировали его полностью, или получите новый в @BotFather (/token).",
        "❌ Telegram rejected this token. Make sure you copied all of it, or get a new one in @BotFather (/token).",
    ),
    "mb_token_network": (
        "⚠️ Не удалось проверить токен — нет связи с Telegram. Пришлите его ещё раз через минуту.",
        "⚠️ Couldn't check the token — no connection to Telegram. Send it again in a minute.",
    ),
    "mb_token_taken": (
        "❌ Этот бот уже запущен. Создайте нового бота в @BotFather и пришлите его токен.",
        "❌ This bot is already running. Create a new bot in @BotFather and send its token.",
    ),
    "mb_started": (
        _card("🎉 Ваш бот запущен!", "🤖 @{username}") +
        "\nОткройте его и отправьте /admin — вы владелец и админ.\n"
        "В админ-панели добавьте товары, а в ⚙️ Настройки укажите свои реквизиты СБП.",
        _card("🎉 Your bot is running!", "🤖 @{username}") +
        "\nOpen it and send /admin — you're the owner and admin.\n"
        "Add products in the admin panel and set your SBP details in ⚙️ Settings.",
    ),
    "mb_start_fail": (
        "⚠️ Бот @{username} не смог запуститься. Администратор уже получил уведомление и поможет.",
        "⚠️ Bot @{username} failed to start. The administrator has been notified and will help.",
    ),
    "mb_failed": (
        "⚠️ Ваш бот @{username} остановлен: он не может подключиться к Telegram. Скорее всего, токен изменили "
        "в @BotFather. Откройте «🤖 Создать своего бота» → «🔑 Новый токен» и пришлите актуальный токен.",
        "⚠️ Your bot @{username} was stopped: it can't connect to Telegram. Most likely the token was changed "
        "in @BotFather. Open «🤖 Create your own bot» → «🔑 New token» and send the current token.",
    ),
    "mb_new_token": (
        "🔑 Пришлите новый токен бота @{username}: в @BotFather отправьте /token и выберите этого бота.",
        "🔑 Send the new token for @{username}: in @BotFather send /token and pick this bot.",
    ),
    # ---------- отзыв, техработы, звёзды, пополнение ----------
    # {link} — ссылка на отзывы, {user} — юзернейм, который нужно указать (⚙️ Настройки)
    "review_ask": (
        "💜 <b>Спасибо за покупку!</b>\n\nОставьте, пожалуйста, отзыв сюда: {link}\nВ отзыве укажите {user} 🙏",
        "💜 <b>Thank you for your purchase!</b>\n\nPlease leave a review here: {link}\nMention {user} in it 🙏",
    ),
    "maint": (
        _card("🛠 Бот на технических работах", "Мы скоро вернёмся! Попробуйте, пожалуйста, чуть позже."),
        _card("🛠 The bot is under maintenance", "We'll be back soon! Please try again a bit later."),
    ),
    "stars_desc": ("Заказ #{oid}: {name}", "Order #{oid}: {name}"),
    "stars_paid": ("⭐ Оплата звёздами получена! Заказ #{oid}.", "⭐ Stars payment received! Order #{oid}."),
    "stars_fail": ("Заказ недоступен — оплата не прошла, звёзды не списаны.",
                   "Order unavailable — payment canceled, no stars were charged."),
    # {name} — товар, {price} — цена, {stock} — остаток, {link} — ссылка на товар
    "restock_post": (
        "🔥 <b>ПОПОЛНЕНИЕ!</b>\n<blockquote>📦 <b>{name}</b>\n💰 Цена: <b>{price}</b>\n📊 В наличии: <b>{stock}</b></blockquote>\n"
        "⚡ Разбирают быстро — успейте забрать!\n👉 {link}",
        "🔥 <b>RESTOCK!</b>\n<blockquote>📦 <b>{name}</b>\n💰 Price: <b>{price}</b>\n📊 In stock: <b>{stock}</b></blockquote>\n"
        "⚡ Selling fast — grab yours!\n👉 {link}",
    ),
    # ---------- «🔐 Верификация Codex» ----------
    "cx_info": (
        "🔐 <b>Верификация Codex</b>\n<blockquote>Получите номер 🇺🇸 <b>+1</b> для подтверждения аккаунта Codex.</blockquote>\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Оплатите — <b>{price}</b> или <b>{stars} ⭐</b>\n"
        "2️⃣ После подтверждения оплаты бот выдаст номер +1\n"
        "3️⃣ Введите номер в Codex и нажмите «📩 Запросить код»\n"
        "4️⃣ Введите код в Codex и нажмите «✅ Подтвердить»\n\n"
        "💰 Ваш баланс: {balance}",
        "🔐 <b>Codex verification</b>\n<blockquote>Get a 🇺🇸 <b>+1</b> number to verify your Codex account.</blockquote>\n"
        "<b>How it works:</b>\n"
        "1️⃣ Pay — <b>{price}</b> or <b>{stars} ⭐</b>\n"
        "2️⃣ Once the payment is confirmed, the bot gives you a +1 number\n"
        "3️⃣ Enter the number in Codex and tap «📩 Get code»\n"
        "4️⃣ Enter the code in Codex and tap «✅ Confirm»\n\n"
        "💰 Your balance: {balance}",
    ),
    "cx_off": ("🔐 Верификация временно недоступна. Загляните чуть позже.",
               "🔐 Verification is temporarily unavailable. Please check back later."),
    "cx_pay": (
        _card("💳 Оплата верификации Codex", "🧾 Заявка #{vid}\n💰 Сумма: <b>{price}</b>") +
        "\n📲 <b>Реквизиты:</b>\n{details}\n\nПереведите <b>точную сумму</b> и нажмите «Я оплатил».",
        _card("💳 Codex verification payment", "🧾 Request #{vid}\n💰 Amount: <b>{price}</b>") +
        "\n📲 <b>Details:</b>\n{details}\n\nTransfer the <b>exact amount</b> and tap «I have paid».",
    ),
    "cx_receipt_sent": ("✅ Чек отправлен администратору.\nПосле проверки бот выдаст вам номер +1.",
                        "✅ Receipt sent to the administrator.\nAfter review the bot will give you a +1 number."),
    "cx_getting": ("⏳ Оплата подтверждена, получаю номер…", "⏳ Payment confirmed, getting a number…"),
    "cx_number": (
        "📱 <b>Ваш номер:</b> <code>+{number}</code>\n<blockquote>1. Введите этот номер в Codex\n"
        "2. Когда Codex отправит SMS, нажмите «📩 Запросить код»</blockquote>\n⏳ Номер действует около 20 минут.",
        "📱 <b>Your number:</b> <code>+{number}</code>\n<blockquote>1. Enter this number in Codex\n"
        "2. When Codex sends the SMS, tap «📩 Get code»</blockquote>\n⏳ The number is valid for about 20 minutes.",
    ),
    "cx_wait": ("⏳ Код ещё не пришёл. Подождите 10–20 секунд и нажмите ещё раз.",
                "⏳ The code hasn't arrived yet. Wait 10–20 seconds and tap again."),
    "cx_code": ("📩 <b>Ваш код:</b> <code>{code}</code>\n\nВведите его в Codex и нажмите «✅ Подтвердить».",
                "📩 <b>Your code:</b> <code>{code}</code>\n\nEnter it in Codex and tap «✅ Confirm»."),
    "cx_done": ("✅ <b>Верификация завершена!</b>", "✅ <b>Verification completed!</b>"),
    "cx_fail": ("⚠️ Сейчас не удалось получить номер. {price} зачислено на ваш баланс — попробуйте позже или напишите в поддержку.",
                "⚠️ Couldn't get a number right now. {price} was credited to your balance — try again later or contact support."),
    "cx_canceled": ("🚫 Номер отменён, {price} зачислено на ваш баланс.", "🚫 Number canceled, {price} credited to your balance."),
    "cx_rejected": ("❌ Оплата верификации (заявка #{vid}) не подтверждена. Если это ошибка — напишите в поддержку.",
                    "❌ Verification payment (request #{vid}) was not confirmed. If this is a mistake, contact support."),
    "cx_code_late": ("Код уже получен — отменить номер нельзя.", "The code was already received — the number can't be canceled."),
    "sbp_in_chat": ("💳 Реквизиты для оплаты отправлены в чат с ботом.", "💳 Payment details were sent to the bot chat."),
}

# Тексты мини-приложения: ключ -> (RU, EN). Тоже меняются в 📝 Все тексты (там они с пометкой 📱),
# поддерживают жирный/курсив и премиум-эмодзи.
APP_TEXTS = {
    "app_balance": ("Баланс", "Balance"),
    "app_bonus_title": ("Ежедневный бонус", "Daily bonus"),
    "app_bonus_ready": ("Заберите +{amount} на баланс", "Claim +{amount} to your balance"),
    "app_bonus_wait": ("Следующий через {left}", "Next one in {left}"),
    "app_bonus_btn": ("Забрать", "Claim"),
    "app_categories": ("Категории", "Categories"),
    "app_catalog": ("Каталог", "Catalog"),
    "app_home": ("Главная", "Home"),
    "app_orders": ("Заказы", "Orders"),
    "app_profile": ("Профиль", "Profile"),
    "app_hits": ("Хиты", "Hits"),
    "app_disc": ("Скидки", "Sale"),
    "app_new": ("Новинки", "New"),
    "app_fav": ("Избранное", "Favorites"),
    "app_search": ("Поиск товаров", "Search products"),
    "app_buy": ("Купить", "Buy"),
    "app_pay_balance": ("С баланса", "From balance"),
    "app_pay_stars": ("Звёздами", "With Stars"),
    "app_pay_sbp": ("По СБП", "Via SBP"),
    "app_topup": ("Пополнить баланс", "Top up balance"),
    "app_in_stock": ("В наличии", "In stock"),
    "app_out": ("Нет в наличии", "Out of stock"),
    "app_notify": ("Уведомить о поступлении", "Notify me"),
    "app_empty": ("Здесь пока пусто", "Nothing here yet"),
    "app_status": ("Статус", "Status"),
    "app_statuses_hint": ("Статус растёт от суммы пополнений и оплат", "Your status grows with top-ups and payments"),
    "app_refs": ("Пригласить друга", "Invite a friend"),
    "app_refs_hint": ("{pct}% с каждой покупки друга", "{pct}% of every friend's purchase"),
    "app_promo": ("Промокод", "Promo code"),
    "app_support": ("Написать в поддержку", "Contact support"),
    "app_theme": ("Тема", "Theme"),
    "app_done": ("Готово! Товар отправлен в чат с ботом", "Done! The product was sent to the bot chat"),
    "app_member_since": ("С нами с {date}", "Member since {date}"),
}

TEXTS.update(APP_TEXTS)

# Статусы ботов клиентов («🤖 Создать своего бота»)
BOT_STATUS = {
    "pending": ("🔎 оплата на проверке", "🔎 payment under review"),
    "wait_token": ("🔑 ждёт токен", "🔑 waiting for token"),
    "running": ("✅ работает", "✅ running"),
    "stopped": ("⏸ остановлен", "⏸ stopped"),
    "failed": ("⚠️ не работает", "⚠️ not working"),
    "rejected": ("❌ оплата отклонена", "❌ payment rejected"),
}

STATUS = {
    "wait_pay": ("⌛ Ожидает оплаты", "⌛ Awaiting payment"),
    "paid": ("💳 Оплачен", "💳 Paid"),
    "pending": ("🔎 Чек на проверке", "🔎 Receipt under review"),
    "manual": ("⏳ Оплачен, ожидает выдачи", "⏳ Paid, awaiting delivery"),
    "done": ("✅ Выполнен", "✅ Completed"),
    "rejected": ("❌ Отклонён", "❌ Rejected"),
    "canceled": ("🚫 Отменён", "🚫 Canceled"),
    "refunded": ("↩️ Возврат на баланс", "↩️ Refunded to balance"),
}

# Кнопки: ключ -> (русский, английский, цвет по умолчанию: "" / primary / success / danger)
BUTTONS = {
    "shop": ("🛍 Открыть магазин", "🛍 Open shop", "primary"),
    "catalog": ("🛍 Каталог", "🛍 Catalog", "primary"),
    "suppliers": ("🏭 Поставщики", "🏭 Suppliers", ""),
    "orders": ("📦 Заказы", "📦 Orders", ""),
    "profile": ("👤 Профиль", "👤 Profile", ""),
    "promo": ("🎟 Промокод", "🎟 Promo code", ""),
    "lang": ("🌐 Язык / Language", "🌐 Язык / Language", ""),
    "reviews": ("⭐ Отзывы", "⭐ Reviews", ""),
    "support": ("💬 Поддержка", "💬 Support", ""),
    "docs": ("📄 Документы", "📄 Documents", ""),
    "hits": ("🔥 Хиты", "🔥 Hits", ""),
    "disc": ("🏷 Скидки", "🏷 Sale", ""),
    "new": ("🆕 Новинки", "🆕 New", ""),
    "recent": ("🕓 Недавно", "🕓 Recent", ""),
    "search": ("🔎 Поиск", "🔎 Search", ""),
    "fav": ("❤️ Избранное", "❤️ Favorites", ""),
    "main_menu": ("🏠 Главное меню", "🏠 Main menu", ""),
    "back": ("◀️ Назад", "◀️ Back", ""),
    "my_orders": ("📦 Мои заказы", "📦 My orders", ""),
    "refs": ("👥 Рефералы", "👥 Referrals", ""),
    "invite": ("📤 Пригласить друга", "📤 Invite a friend", "success"),
    "refresh": ("🔄 Обновить", "🔄 Refresh", ""),
    "withdraw": ("💸 Вывести", "💸 Withdraw", ""),
    "topup": ("💳 Пополнить баланс", "💳 Top up balance", "success"),
    "bonus": ("🎁 Ежедневный бонус", "🎁 Daily bonus", "primary"),
    "statuses": ("🏅 Статусы", "🏅 Statuses", ""),
    "topup_custom": ("✏️ Своя сумма", "✏️ Custom amount", ""),
    "sup_write": ("✍️ Дописать сообщение", "✍️ Add a message", "primary"),
    "sup_close": ("✅ Вопрос решён", "✅ Issue resolved", "success"),
    "sup_reply": ("✍️ Ответить", "✍️ Reply", "primary"),
    "buy": ("🛒 Купить", "🛒 Buy", "success"),
    "qty_confirm": ("✅ Оформить заказ", "✅ Checkout", "success"),
    "qty_input": ("✏️ Ввести число", "✏️ Enter number", ""),
    "notify": ("🔔 Уведомить о поступлении", "🔔 Notify me", "primary"),
    "fav_add": ("🤍 В избранное", "🤍 Add to favorites", ""),
    "fav_del": ("❤️ В избранном", "❤️ In favorites", ""),
    "pay_balance": ("💰 С баланса", "💰 From balance", ""),
    "pay_sbp": ("💳 СБП", "💳 SBP", ""),
    "paid": ("✅ Я оплатил", "✅ I have paid", "success"),
    "cancel": ("❌ Отмена", "❌ Cancel", "danger"),
    "sub_check": ("✅ Проверить подписку", "✅ Check subscription", "success"),
    "legal_privacy": ("🔒 Политика", "🔒 Privacy", ""),
    "legal_terms": ("📜 Соглашение", "📜 Terms", ""),
    "agree": ("✅ Принимаю", "✅ I agree", "success"),
    "mkbot": ("🤖 Создать своего бота", "🤖 Create your own bot", "primary"),
    "mb_read": ("✅ Я прочитал", "✅ I've read it", "success"),
    "mb_token": ("🔑 Новый токен", "🔑 New token", ""),
    "pay_stars": ("⭐ Звёздами", "⭐ Stars", ""),
    "codex": ("🔐 Верификация Codex", "🔐 Codex verification", "primary"),
    "cx_sbp": ("💳 Оплатить по СБП", "💳 Pay via SBP", ""),
    "cx_stars": ("⭐ Оплатить звёздами", "⭐ Pay with Stars", ""),
    "cx_balance": ("💰 Оплатить с баланса", "💰 Pay from balance", ""),
    "cx_get_code": ("📩 Запросить код", "📩 Get code", "primary"),
    "cx_confirm": ("✅ Подтвердить", "✅ Confirm", "success"),
    "cx_cancel_num": ("❌ Отменить номер", "❌ Cancel number", "danger"),
    "open_product": ("🛒 Открыть товар", "🛒 Open product", "success"),
}

# Все тексты бота можно поменять в админ-панели → ✏️ Оформление → 📝 Все тексты.
# Названия в списке — понятные для главных текстов, для остальных — начало самого текста.
_TEXT_TITLES = {
    "welcome": "👋 Приветствие",
    "profile": "👤 Профиль",
    "catalog_title": "🛍 Заголовок каталога",
    "mb_info": "🤖 Создать своего бота",
    "cx_info": "🔐 Верификация Codex",
    "review_ask": "💜 Просьба об отзыве",
    "restock_post": "🔥 Рассылка о пополнении",
    "maint": "🛠 Технические работы",
    "sup_prompt": "💬 Поддержка: приглашение",
    "topup_title": "💳 Пополнение баланса",
}


def _short_title(key):
    import re
    first = re.sub(r"<[^>]+>|\{[^}]+\}", "", TEXTS[key][0]).strip().split("\n")[0].strip()
    first = (first[:32] + "…") if len(first) > 33 else (first or key)
    return ("📱 " + first) if key.startswith("app_") else first


EDITABLE_TEXTS = {k: _TEXT_TITLES.get(k) or _short_title(k) for k in TEXTS
                  if not (config.CHILD and k.startswith("mb_"))}


def bot_status(st, lang):
    pair = BOT_STATUS.get(st, (st, st))
    return pair[1] if lang == "en" else pair[0]


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def t(key, lang="ru", **kw):
    s = db.get_setting(f"t:{key}:{lang}")
    if s is None:
        pair = TEXTS[key]
        s = pair[1] if lang == "en" else pair[0]
    if not kw:
        return s
    try:
        return s.format_map(_Safe(kw))
    except (ValueError, IndexError, KeyError, AttributeError):  # в тексте админа попались одиночные { }
        return s


def bt(key, lang="ru"):
    s = db.get_setting(f"b:{key}:{lang}")
    if s is None:
        ru, en, _ = BUTTONS[key]
        s = en if lang == "en" else ru
    return s


def status(st, lang):
    pair = STATUS.get(st, (st, st))
    return pair[1] if lang == "en" else pair[0]


def money(v):
    v = round(float(v or 0), 2)
    return (f"{int(v)}" if v == int(v) else f"{v:.2f}") + "₽"


def plural(n, lang):
    if lang == "en":
        return "product" if n == 1 else "products"
    if n % 10 == 1 and n % 100 != 11:
        return "товар"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "товара"
    return "товаров"


def fdate(s):
    # "2026-09-29 12:00:00" -> "29.09.2026"
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if s and len(s) >= 10 else "—"


def bar(pct, width=12):
    """Полоска прогресса для профиля: ▰▰▰▱▱▱"""
    n = round(pct / 100 * width)
    return "▰" * n + "▱" * (width - n)
