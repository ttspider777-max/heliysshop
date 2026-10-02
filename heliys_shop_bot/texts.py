import db

# Тексты интерфейса: ключ -> (русский, английский).
# Тексты из EDITABLE_TEXTS админ может переопределить в админ-панели (с премиум-эмодзи).
TEXTS = {
    "welcome": ("heliys 𝗌𝗁𝗈𝗉", "heliys 𝗌𝗁𝗈𝗉"),
    "catalog_title": ("🛍 <b>Каталог heliys shop</b>", "🛍 <b>heliys shop catalog</b>"),
    "catalog_body": (
        "🔥 <b>Хиты</b> — по реальным покупкам\n"
        "🏷 <b>Скидки</b> — только активные предложения\n"
        "🔎 <b>Поиск</b> — по названию и описанию",
        "🔥 <b>Hits</b> — based on real purchases\n"
        "🏷 <b>Sale</b> — active offers only\n"
        "🔎 <b>Search</b> — by name and description",
    ),
    "list_cat": ("{name}\n\nВыберите товар:", "{name}\n\nChoose a product:"),
    "list_hits": ("🔥 <b>Хиты</b>\n\nСамые покупаемые товары прямо сейчас:", "🔥 <b>Hits</b>\n\nBest-selling products right now:"),
    "list_disc": ("🏷 <b>Скидки</b>\n\nТолько активные предложения:", "🏷 <b>Sale</b>\n\nActive offers only:"),
    "list_new": ("🆕 <b>Новинки</b>\n\nНедавно добавленные товары:", "🆕 <b>New</b>\n\nRecently added products:"),
    "list_recent": ("🕓 <b>Недавно</b>\n\nТовары, которые вы смотрели:", "🕓 <b>Recent</b>\n\nProducts you viewed:"),
    "list_fav": ("❤️ <b>Избранное</b>", "❤️ <b>Favorites</b>"),
    "list_srch": ("🔎 <b>Результаты поиска:</b> {q}", "🔎 <b>Search results:</b> {q}"),
    "list_empty": ("\n\n<i>Здесь пока пусто 🤷</i>", "\n\n<i>Nothing here yet 🤷</i>"),
    "search_prompt": ("🔎 Введите название или часть описания товара:", "🔎 Enter a product name or part of its description:"),
    "price": ("💰 Цена: <b>{price}</b>", "💰 Price: <b>{price}</b>"),
    "price_disc": ("💰 Цена: <s>{old}</s> <b>{price}</b>  (−{pct}%)", "💰 Price: <s>{old}</s> <b>{price}</b>  (−{pct}%)"),
    "promo_applied": ("🎟 С промокодом <code>{code}</code>: <b>{price}</b>", "🎟 With promo <code>{code}</code>: <b>{price}</b>"),
    "stock": ("📦 В наличии: {n} шт.", "📦 In stock: {n} pcs."),
    "multi_hint": ("🔢 Можно купить сразу несколько штук", "🔢 You can buy several at once"),
    "stock_manual": ("📦 В наличии", "📦 In stock"),
    "stock_out": ("❌ Нет в наличии", "❌ Out of stock"),
    "not_found": ("Товар не найден", "Product not found"),
    "out_alert": ("❌ Товара нет в наличии. Нажмите «Уведомить о поступлении».", "❌ Out of stock. Tap «Notify me»."),
    "choose_pay": (
        "🧾 <b>Оформление заказа</b>\n\n📦 Товар: {name}\n💰 К оплате: <b>{price}</b>\n💳 Ваш баланс: {balance}\n\nВыберите способ оплаты:",
        "🧾 <b>Checkout</b>\n\n📦 Product: {name}\n💰 To pay: <b>{price}</b>\n💳 Your balance: {balance}\n\nChoose a payment method:",
    ),
    "no_money": ("❌ Недостаточно средств на балансе", "❌ Insufficient balance"),
    "paid_balance": ("✅ Заказ #{oid} оплачен с баланса. Товар отправлен ниже 👇", "✅ Order #{oid} paid from balance. Product sent below 👇"),
    "sbp_text": (
        "💳 <b>Оплата по СБП</b>\n\n🧾 Заказ #{oid}\n📦 Товар: {name}\n💰 Сумма: <b>{price}</b>\n\n📲 Реквизиты:\n{details}\n\n"
        "Переведите <b>точную сумму</b> и нажмите «Я оплатил».",
        "💳 <b>SBP payment</b>\n\n🧾 Order #{oid}\n📦 Product: {name}\n💰 Amount: <b>{price}</b>\n\n📲 Details:\n{details}\n\n"
        "Transfer the <b>exact amount</b> and tap «I have paid».",
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
        "✅ <b>Заказ #{oid} выполнен!</b>\n\n📦 Товар: {name}\n\n🔑 Ваши данные:\n<code>{content}</code>\n\nСпасибо за покупку! 💜",
        "✅ <b>Order #{oid} completed!</b>\n\n📦 Product: {name}\n\n🔑 Your data:\n<code>{content}</code>\n\nThank you for your purchase! 💜",
    ),
    "order_delivered_file": (
        "✅ <b>Заказ #{oid} выполнен!</b>\n\n📦 Товар: {name}\n\n🔑 Ваши данные — в файле выше.\nСпасибо за покупку! 💜",
        "✅ <b>Order #{oid} completed!</b>\n\n📦 Product: {name}\n\n🔑 Your data is in the attached file.\nThank you for your purchase! 💜",
    ),
    "qty_title": (
        "🛒 <b>{name}</b>\n\n💰 Цена за шт.: <b>{price}</b>\n📦 Доступно: {avail}\n\n"
        "Выберите количество:\n\n🔢 Количество: <b>{qty}</b>\n💳 Итого: <b>{total}</b>",
        "🛒 <b>{name}</b>\n\n💰 Price per item: <b>{price}</b>\n📦 Available: {avail}\n\n"
        "Choose quantity:\n\n🔢 Quantity: <b>{qty}</b>\n💳 Total: <b>{total}</b>",
    ),
    "qty_avail_manual": ("в любом количестве", "any amount"),
    "qty_avail_n": ("{n} шт.", "{n} pcs."),
    "qty_prompt": ("✏️ Введите нужное количество (от 1 до {max}):", "✏️ Enter the quantity (1 to {max}):"),
    "qty_bad": ("❌ Введите число от 1 до {max}", "❌ Enter a number from 1 to {max}"),
    "qty_max": ("Максимум — {max} шт.", "Maximum is {max} pcs."),
    "qty_min": ("Минимум — 1 шт.", "Minimum is 1 pc."),
    "order_manual": (
        "✅ Оплата заказа #{oid} подтверждена!\nАдминистратор выдаст товар в ближайшее время.",
        "✅ Payment for order #{oid} confirmed!\nThe administrator will deliver the product shortly.",
    ),
    "order_refunded": (
        "⚠️ Товар по заказу #{oid} закончился. {price} зачислено на ваш баланс.",
        "⚠️ The product for order #{oid} ran out. {price} was credited to your balance.",
    ),
    "notify_on": ("🔔 Мы сообщим, когда товар появится в наличии", "🔔 We'll let you know when it's back in stock"),
    "notify_arrived": ("🔔 <b>Товар снова в наличии!</b>\n\n📦 {name}", "🔔 <b>Back in stock!</b>\n\n📦 {name}"),
    "fav_added": ("❤️ Добавлено в избранное", "❤️ Added to favorites"),
    "fav_removed": ("💔 Удалено из избранного", "💔 Removed from favorites"),
    "orders_title": ("📦 <b>Ваши заказы</b> — {n}", "📦 <b>Your orders</b> — {n}"),
    "orders_empty": ("\n\n<i>У вас пока нет заказов.</i>", "\n\n<i>You have no orders yet.</i>"),
    "order_detail": (
        "🧾 <b>Заказ #{oid}</b>\n\n📦 Товар: {name}\n💰 Сумма: {price}\n💳 Оплата: {method}\n📅 Дата: {date}\n📍 Статус: {status}",
        "🧾 <b>Order #{oid}</b>\n\n📦 Product: {name}\n💰 Amount: {price}\n💳 Payment: {method}\n📅 Date: {date}\n📍 Status: {status}",
    ),
    "order_content": ("\n\n🔑 Данные:\n<code>{content}</code>", "\n\n🔑 Data:\n<code>{content}</code>"),
    "profile": (
        "👤 <b>Профиль</b>\n\n🆔 ID: <code>{id}</code>\n📅 В боте с: {date}\n🛒 Заказов: {orders}\n\n💰 Баланс: <b>{balance}</b>",
        "👤 <b>Profile</b>\n\n🆔 ID: <code>{id}</code>\n📅 Member since: {date}\n🛒 Orders: {orders}\n\n💰 Balance: <b>{balance}</b>",
    ),
    "profile_promo": ("\n🎟 Активный промокод: <code>{code}</code> (−{pct}%)", "\n🎟 Active promo: <code>{code}</code> (−{pct}%)"),
    "refs": (
        "👥 <b>Реферальная программа</b>\n\n🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        "👤 Приглашено: <b>{invited}</b>\n🛒 Купили: <b>{bought}</b>\n💸 Заработано: <b>{earned}</b>\n"
        "💰 Доступно к выводу: <b>{available}</b>\n\n"
        "<i>Вы получаете {pct}% с каждой покупки приглашённых. Вывод — на баланс бота через заявку администратору, минимум {min}.</i>",
        "👥 <b>Referral program</b>\n\n🔗 Your link:\n<code>{link}</code>\n\n"
        "👤 Invited: <b>{invited}</b>\n🛒 Bought: <b>{bought}</b>\n💸 Earned: <b>{earned}</b>\n"
        "💰 Available to withdraw: <b>{available}</b>\n\n"
        "<i>You get {pct}% of every purchase made by your referrals. Withdrawal goes to your bot balance via admin request, minimum {min}.</i>",
    ),
    "invite_text": ("Заходи в heliys shop 🔥", "Check out heliys shop 🔥"),
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
        "📢 <b>Подпишитесь, чтобы пользоваться ботом</b>\n\nПодпишитесь на каналы ниже и нажмите «Проверить подписку».",
        "📢 <b>Subscribe to use the bot</b>\n\nSubscribe to the channels below and tap «Check subscription».",
    ),
    "sub_not_yet": ("❌ Вы ещё не подписались на все каналы", "❌ You haven't subscribed to all channels yet"),
    "sub_thanks": ("✅ Спасибо за подписку!", "✅ Thanks for subscribing!"),
    "banned": ("🚫 Вы заблокированы в этом боте.", "🚫 You are banned from this bot."),
    "m_balance": ("Баланс", "Balance"),
    "m_sbp": ("СБП", "SBP"),
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
    "catalog": ("🛍 Каталог", "🛍 Catalog", "primary"),
    "suppliers": ("🏭 Поставщики", "🏭 Suppliers", ""),
    "orders": ("📦 Заказы", "📦 Orders", ""),
    "profile": ("👤 Профиль", "👤 Profile", ""),
    "promo": ("🎟 Промокод", "🎟 Promo code", ""),
    "lang": ("🌐 Язык / Language", "🌐 Язык / Language", ""),
    "reviews": ("⭐ Отзывы", "⭐ Reviews", ""),
    "support": ("💬 Поддержка", "💬 Support", ""),
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
}

EDITABLE_TEXTS = {
    "welcome": "👋 Приветствие",
    "catalog_title": "🛍 Заголовок каталога",
}


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def t(key, lang="ru", **kw):
    s = db.get_setting(f"t:{key}:{lang}")
    if s is None:
        pair = TEXTS[key]
        s = pair[1] if lang == "en" else pair[0]
    return s.format_map(_Safe(kw)) if kw else s


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
