"""Telegram development bot; only use with a separate test bot token."""
import asyncio
import time
from html import escape
from urllib.parse import urlparse
from uuid import uuid4
import aiohttp
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from app.core.config import settings
from app.auth import bot_session, mint_telegram_session, revoke_session

bot = Bot(token=settings.bot_token) if settings.bot_token else None
dp = Dispatcher()
# Do not display account information or accept private requests in groups.
dp.message.filter(F.chat.type == "private")
dp.callback_query.filter(F.message.chat.type == "private")

class TelegramIdentityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Only private updates obtained by the bot's authenticated getUpdates poller.
        item=event.message or event.callback_query
        chat = item.chat if event.message else (item.message.chat if item and item.message else None)
        if not item or not item.from_user or not chat or chat.type != 'private':
            return await handler(event, data)
        if chat.id != item.from_user.id:
            return None
        try:
            raw=await asyncio.to_thread(mint_telegram_session, item.from_user.id, item.from_user.username)
        except PermissionError:
            if event.message: await item.answer('Аккаунт отключён. Обратитесь к владельцу системы.')
            else: await item.answer('Аккаунт отключён.', show_alert=True)
            return None
        token=bot_session.set(raw)
        try: return await handler(event,data)
        finally:
            bot_session.reset(token)
            await asyncio.to_thread(revoke_session,raw)

dp.update.outer_middleware(TelegramIdentityMiddleware())

class DeviceForm(StatesGroup):
    waiting_for_code = State()
    waiting_for_confirmation = State()

class LicenseForm(StatesGroup):
    waiting_for_key = State()

class AdminForm(StatesGroup):
    confirm = State()

class SupportForm(StatesGroup):
    waiting_for_message = State()
    waiting_for_reply = State()
    waiting_for_admin_reply = State()

class ApiError(Exception):
    pass

def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in rows])

def main_keyboard():
    return keyboard([
        [("🎮 Подключить игру", "connect")],
        [("👤 Мой аккаунт", "account"), ("🔔 Уведомления", "notifications")],
        [("💎 Подписка", "subscription"), ("📱 Устройства", "devices")],
        [("🔑 Активировать ключ", "license_activate")],
        [("📚 Инструкция", "help"), ("🛟 Поддержка", "support")],
    ])

async def api(method, path, body=None):
    credential=bot_session.get()
    if not credential:
        raise ApiError("Сессия пользователя недоступна")
    url = settings.api_base_url.rstrip("/") + path
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.request(method, url, json=body, headers={"Authorization": f"Bearer {credential}"}) as response:
                if response.status >= 400:
                    raise ApiError(f"API недоступен или отклонил запрос (HTTP {response.status})")
                return await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise ApiError("Нет связи с API") from exc

async def show(call: CallbackQuery, text: str, markup=None):
    await call.message.edit_text(text, reply_markup=markup or main_keyboard(), parse_mode="HTML")
    await call.answer()

async def fail(call: CallbackQuery, exc: ApiError):
    await call.answer(str(exc), show_alert=True)

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    try:
        await api("POST", "/v1/users", {"telegram_id": message.from_user.id, "username": message.from_user.username})
        status = "Аккаунт зарегистрирован в тестовой базе."
    except ApiError:
        status = "Сервер недоступен: данные аккаунта не проверены."
    await message.answer("🖤 <b>NØRI — GAMING ECOSYSTEM</b>\n\n" + status +
                         "\n🎮 Реальное подключение к игре пока недоступно.\nВыбери раздел:",
                         reply_markup=main_keyboard(), parse_mode="HTML")

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(call, "🖤 <b>NØRI — GAMING ECOSYSTEM</b>\n\nВыбери раздел:")

@dp.callback_query(F.data == "connect")
async def connect(call: CallbackQuery):
    await show(call, "🎮 <b>ПОДКЛЮЧЕНИЕ ИГРЫ</b>\n\nВыбери платформу:", keyboard([
        [("Hassle RP 2.0", "platform_hassle")], [("Radmir CRMP", "platform_radmir")], [("◀️ Главное меню", "home")]]))

@dp.callback_query(F.data.in_({"platform_hassle", "platform_radmir"}))
async def platform(call: CallbackQuery):
    name = "Hassle RP 2.0" if call.data == "platform_hassle" else "Radmir CRMP"
    text = f"🎮 <b>{name}</b>\n\nРеальный игровой интерфейс не подтверждён и недоступен. Никакие данные игры не подключены."
    rows=[]
    text += "\n\nДля привязки введи одноразовый код из клиента. Это не подключает игру."
    rows.append([("Ввести код устройства", "pair_enter")])
    rows += [[("◀️ Назад", "connect")], [("Главное меню", "home")]]
    await show(call,text,keyboard(rows))

@dp.callback_query(F.data == "pair_enter")
async def pair_enter(call: CallbackQuery, state: FSMContext):
    await state.set_state(DeviceForm.waiting_for_code)
    await show(call,"Отправь одноразовый код устройства. Пароли и секрет устройства не нужны. Отмена: /cancel.")

@dp.message(DeviceForm.waiting_for_code, F.text)
async def pair_code(message: Message, state: FSMContext):
    code=message.text.strip().upper()
    if len(code)!=16 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in code):
        await message.answer("Код должен содержать 16 символов A–Z и 2–7. Отмена: /cancel.")
        return
    try:
        preview=await api("POST","/v2/pairings/preview",{"pairing_code":code})
        licenses=(await api("GET",f"/v1/users/{message.from_user.id}/licenses"))["licenses"]
        platform={'hassle_rp_2':'hassle','radmir_crmp':'radmir'}[preview['platform']]
        eligible=[x for x in licenses if x.get('access',{}).get('allowed') and x.get('entitlement',{}).get('plan_id') and x['entitlement'].get('platform') in ('both',platform)]
        if not eligible:
            await state.clear();await message.answer("Нет подходящей лицензии с подтверждённым тарифом. Обратитесь в поддержку.",reply_markup=main_keyboard());return
        await state.update_data(pairing_id=preview['pairing_id'],pairing_code=code)
        await state.set_state(DeviceForm.waiting_for_confirmation)
        try: await message.delete()
        except Exception: pass
        rows=[[(f"Подтвердить с лицензией №{item['id']}",f"pairconfirm:{item['id']}")] for item in eligible[:20]]
        rows.append([("Отмена","home")])
        await message.answer(f"Проверь устройство: <b>{escape(preview['name'])}</b> · {escape(preview['platform'])} · …{escape(preview['device_id_suffix'])}.\nПодтверждай только своё устройство:",reply_markup=keyboard(rows),parse_mode="HTML")
    except ApiError:
        await state.clear();await message.answer("Код недоступен или истёк. Начни привязку заново.",reply_markup=main_keyboard())

@dp.callback_query(DeviceForm.waiting_for_confirmation, F.data.startswith("pairconfirm:"))
async def pair_confirm(call: CallbackQuery, state: FSMContext):
    data=await state.get_data()
    try:
        grant=int(call.data.split(':',1)[1])
        await api("POST","/v2/pairings/confirm",{"pairing_id":data['pairing_id'],"pairing_code":data['pairing_code'],"license_id":grant})
        await state.clear();await show(call,"Устройство подтверждено; клиент должен получить индивидуальный credential до истечения срока. Игра не подключена.")
    except (ApiError,ValueError,KeyError):
        await state.clear();await show(call,"Не удалось подтвердить привязку: проверь лицензию, срок и лимит устройств.")

@dp.callback_query(F.data == "account")
async def account(call: CallbackQuery):
    try:
        data = await api("GET", f"/v1/users/{call.from_user.id}")
        licenses = await api("GET", f"/v1/users/{call.from_user.id}/licenses")
        devices = await api("GET", f"/v1/users/{call.from_user.id}/devices")
        device_count = sum(1 for item in devices["devices"] if item["status"] == "active")
        active = sum(1 for item in licenses["licenses"] if item.get("access", {}).get("allowed"))
        name = "@" + escape(data["username"]) if data["username"] else "не указан"
        await show(call, f"👤 <b>МОЙ АККАУНТ</b>\n\nПользователь: {name}\nTelegram ID: <code>{data['telegram_id']}</code>\n"
                   f"Регистрация: {escape(str(data['created_at']))}\nАктивные тестовые лицензии: {active}\nАктивные устройства: {device_count} (не означает, что игра подключена)")
    except ApiError as exc:
        await fail(call, exc)

KINDS = {"sms": "SMS", "calls": "Звонки", "ads": "Объявления", "queue": "Очередь", "system": "Системные"}

@dp.callback_query(F.data == "notifications")
async def notifications(call: CallbackQuery):
    await show(call, "🔔 <b>НАСТРОЙКИ УВЕДОМЛЕНИЙ</b>\n\nВыбери платформу. Настройки сохраняются, но доставка игровых событий ещё не реализована.",
               keyboard([[("Hassle RP 2.0", "settings_hassle")], [("Radmir CRMP", "settings_radmir")], [("История уведомлений", "notification_history")], [("◀️ Главное меню", "home")]]))

async def render_settings(call: CallbackQuery, platform_name: str):
    try:
        data = await api("GET", f"/v1/users/{call.from_user.id}/settings")
        chosen = {x["kind"]: x["enabled"] for x in data["settings"] if x["platform"] == platform_name}
        rows = [[(f"{'✅' if chosen.get(kind, False) else '⬜'} {label}", f"toggle:{platform_name}:{kind}:{0 if chosen.get(kind, False) else 1}")] for kind, label in KINDS.items()]
        rows.append([("◀️ Назад", "notifications")])
        await show(call, "🔔 <b>УВЕДОМЛЕНИЯ</b>\n\nНастройки сохраняются. Игровые уведомления ещё не подключены; системные управляют уведомлениями поддержки.", keyboard(rows))
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data == "notification_history")
async def notification_history(call: CallbackQuery):
    try:
        result = await api("GET", f"/v1/users/{call.from_user.id}/notifications")
        rows = [f"Обращение №{item['ticket_id']}: {escape(item['status'])}" for item in result["notifications"][:20]]
        await show(call, "🔔 <b>ИСТОРИЯ УВЕДОМЛЕНИЙ</b>\n\n" + ("\n".join(rows) if rows else "Уведомлений пока нет.") + "\n\nsent означает приём Telegram API, но не прочтение.", keyboard([[("◀️ Назад", "notifications")]]))
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data.in_({"settings_hassle", "settings_radmir"}))
async def settings_page(call: CallbackQuery):
    await render_settings(call, call.data.split("_", 1)[1])

@dp.callback_query(F.data.startswith("toggle:"))
async def toggle(call: CallbackQuery):
    parts = call.data.split(":")
    if len(parts) != 4 or parts[1] not in {"hassle", "radmir"} or parts[2] not in KINDS or parts[3] not in {"0", "1"}:
        await call.answer("Некорректная кнопка", show_alert=True)
        return
    try:
        await api("PUT", f"/v1/users/{call.from_user.id}/settings/{parts[1]}/{parts[2]}", {"enabled": parts[3] == "1"})
        await render_settings(call, parts[1])
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data == "subscription")
async def subscription(call: CallbackQuery):
    try:
        result = await api("GET", f"/v1/users/{call.from_user.id}/licenses")
        plans = await api("GET", "/v1/plans")
        plan_lines = [f"{escape(p['name'])}: {p['price_minor']} мин. ед. {escape(p['currency'])} / {p['duration_days']} дн." for p in plans['plans'][:10]]
        lines = [f"№{x['id']}: {escape(x['status'])}; до {escape(str(x['expires_at'] or 'активации'))}" for x in result['licenses']]
        await show(call, "💎 <b>ТЕСТОВЫЕ ЛИЦЕНЗИИ</b>\n\n" + ("\n".join(lines) if lines else "Лицензий нет.") +
                   "\n\nТарифы:\n" + ("\n".join(plan_lines) if plan_lines else "Тарифы не настроены.") +
                   "\n\nПлатежи и доступ к игровому плагину не подключены.",
                   keyboard([[("🔑 Активировать ключ", "license_activate")], [("◀️ Главное меню", "home")]]))
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data == "license_activate")
async def ask_license(call: CallbackQuery, state: FSMContext):
    await state.set_state(LicenseForm.waiting_for_key)
    await show(call, "🔑 Отправь тестовый ключ лицензии. Ключ должен быть выдан для твоего Telegram ID. Отмена: /cancel.",
               keyboard([[("◀️ Отмена", "home")]]))

@dp.message(LicenseForm.waiting_for_key, F.text)
async def activate_license(message: Message, state: FSMContext):
    key = message.text.strip()
    if len(key) < 10 or len(key) > 100:
        await message.answer("Формат ключа неверный. Попробуй ещё раз или /cancel.")
        return
    try:
        result = await api("POST", f"/v1/users/{message.from_user.id}/licenses/activate", {"key": key})
        await state.clear()
        # Delete the key message on a best-effort basis; Telegram may retain it.
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(f"Лицензия №{result['id']}: {result['status']}. Срок: {result['expires_at']}. Это тестовый контур.", reply_markup=main_keyboard())
    except ApiError:
        await message.answer("Не удалось активировать ключ. Проверь ключ и соединение или /cancel.")

def admin_keyboard():
    return keyboard([[("👥 Пользователи", "admin_users")], [("🔑 Лицензии", "admin_licenses"), ("💎 Тарифы", "admin_plans")],
                     [("🛟 Обращения", "admin_support"), ("⚠️ Ошибки", "admin_errors")], [("◀️ Главное меню", "home")]])

@dp.message(Command("admin"))
async def admin_menu_message(message: Message):
    try:
        await api("GET",f"/v1/admin/access?actor_telegram_id={message.from_user.id}")
        await message.answer("👑 <b>АДМИНИСТРИРОВАНИЕ NØRI</b>\n\nВыбери раздел. Тестовый контур; платёжные и игровые функции не подключены.",reply_markup=admin_keyboard(),parse_mode="HTML")
    except ApiError:
        await message.answer("Панель недоступна: проверь права и подключение.")

@dp.callback_query(F.data.in_({"admin_menu", "admin_licenses", "admin_plans", "admin_support", "admin_errors", "admin_users"}))
async def admin_navigation(call: CallbackQuery):
    try:
        await api("GET",f"/v1/admin/access?actor_telegram_id={call.from_user.id}")
        if call.data == 'admin_users':
            users=(await api('GET','/v1/admin/users'))['users']
            rows=[[(f"{u['telegram_id']} · {u['role']}{' · ⛔' if u['disabled'] else ''}",f"au:{u['telegram_id']}")] for u in users[:25]]
            rows.append([('◀️ Админ-меню','admin_menu')])
            await show(call,'👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n\nПоследние 25 зарегистрированных:',keyboard(rows))
        elif call.data == 'admin_licenses':
            await show(call,"🔑 <b>ЛИЦЕНЗИИ</b>\n\n/issue TELEGRAM_ID ДНЕЙ — выдать\n/extend ID_ЛИЦЕНЗИИ ДНЕЙ — продлить\n/revoke ID_ЛИЦЕНЗИИ — отозвать\n/grantplan TELEGRAM_ID ID_ТАРИФА — выдать по тарифу",keyboard([[("◀️ Админ-меню","admin_menu")]]))
        elif call.data == 'admin_plans':
            plans=(await api("GET","/v1/admin/plans"))['plans']
            lines=[f"{escape(p['name'])} · {p['id']} · {'вкл' if p['enabled'] else 'выкл'}" for p in plans[:10]]
            plan_rows=[[(p['name'][:25],f"ap:{p['id']}")] for p in plans[:10]]
            plan_rows.append([('◀️ Админ-меню','admin_menu')])
            await show(call,"💎 <b>ТАРИФЫ</b>\n\n"+("\n".join(lines) if lines else "Тарифы не созданы.")+"\n\nСоздать: /plancreate НАЗВАНИЕ ЦЕНА_В_МИН_ЕД ВАЛЮТА ДНЕЙ УСТРОЙСТВ ПЛАТФОРМА (both/hassle/radmir). Оплата пока недоступна.",keyboard(plan_rows))
        elif call.data == 'admin_errors':
            errors=(await api("GET",f"/v1/admin/errors?actor_telegram_id={call.from_user.id}"))['errors']
            lines=[f"№{e['id']} · {escape(e['component'])} · {escape(e['code'])}" for e in errors[:20]]
            await show(call,"⚠️ <b>ОШИБКИ WORKER</b>\n\n"+("\n".join(lines) if lines else "Ошибок нет."),keyboard([[("◀️ Админ-меню","admin_menu")]]))
        elif call.data == 'admin_support':
            tickets=(await api("GET",f"/v1/admin/tickets?actor_telegram_id={call.from_user.id}"))['tickets']
            rows=[[(f"№{t['id']} · {t['category']}",f"admin_ticket:{t['id']}")] for t in tickets[:30]]
            rows.append([("◀️ Админ-меню","admin_menu")])
            await show(call,"🛟 <b>ОТКРЫТЫЕ ОБРАЩЕНИЯ</b>\n\n"+("Выбери обращение." if tickets else "Обращений нет."),keyboard(rows))
        else:
            await show(call,"👑 <b>АДМИНИСТРИРОВАНИЕ NØRI</b>\n\nВыбери раздел.",admin_keyboard())
    except ApiError as exc: await fail(call,exc)

@dp.message(Command("plancreate"))
async def admin_plan_create(message: Message,state: FSMContext):
    parts=(message.text or '').split()
    if len(parts)!=7 or not all(parts[i].isdigit() for i in (2,4,5)) or len(parts[3])!=3 or not parts[3].isalpha() or parts[6] not in {'both','hassle','radmir'}:
        await message.answer("Формат: /plancreate НАЗВАНИЕ ЦЕНА_В_МИН_ЕД ВАЛЮТА ДНЕЙ УСТРОЙСТВ both|hassle|radmir")
        return
    try:
        await api("GET",f"/v1/admin/access?actor_telegram_id={message.from_user.id}")
    except ApiError:
        await message.answer("Нет доступа к панели администратора.")
        return
    await state.set_state(AdminForm.confirm)
    await state.update_data(action='plan',target=0,request_id=str(uuid4()),expires=time.time()+300,
                            plan={'name':parts[1],'price_minor':int(parts[2]),'currency':parts[3].upper(),'duration_days':int(parts[4]),'device_limit':int(parts[5]),'platform':parts[6]})
    await message.answer(f"Создать тариф {parts[1]} за {parts[2]} минимальных единиц {parts[3].upper()} на {parts[4]} дней?",reply_markup=keyboard([[("Подтвердить","admin_confirm"),("Отмена","admin_cancel")]]))

@dp.message(Command('grantplan'))
async def admin_grant_plan(message:Message,state:FSMContext):
    from uuid import UUID
    parts=(message.text or '').split()
    try:
        if len(parts)!=3 or not parts[1].isdigit() or int(parts[1])<=0: raise ValueError()
        plan_id=str(UUID(parts[2]))
        await api('GET',f'/v1/admin/access?actor_telegram_id={message.from_user.id}')
    except ValueError:
        return await message.answer('Формат: /grantplan TELEGRAM_ID ID_ТАРИФА')
    except ApiError:
        return await message.answer('Нет доступа к панели администратора.')
    await state.set_state(AdminForm.confirm)
    await state.update_data(action='issue_plan',target=int(parts[1]),plan_id=plan_id,request_id=str(uuid4()),expires=time.time()+300)
    await message.answer(f'Выдать пользователю {parts[1]} лицензию по тарифу {plan_id}? Оплата не проводится.',reply_markup=keyboard([[('Выдать','admin_confirm'),('Отмена','admin_cancel')]]))

@dp.message(Command("issue", "revoke", "extend"))
async def admin_action(message: Message, state: FSMContext):
    parts = (message.text or "").split()
    action = parts[0].split("@", 1)[0][1:].lower()
    count = 3 if action in {"issue", "extend"} else 2
    if len(parts) != count or not all(x.isdigit() and int(x) > 0 for x in parts[1:]):
        await message.answer("Формат: /issue TELEGRAM_ID ДНЕЙ, /extend ID_ЛИЦЕНЗИИ ДНЕЙ или /revoke ID_ЛИЦЕНЗИИ")
        return
    if count == 3 and int(parts[2]) > 3650:
        await message.answer("Число дней должно быть от 1 до 3650.")
        return
    await state.set_state(AdminForm.confirm)
    await state.update_data(action=action, target=int(parts[1]), days=int(parts[2]) if count == 3 else 0,
                            request_id=str(uuid4()), expires=time.time()+300)
    description = {"issue": "Выдать ключ пользователю", "revoke": "Отозвать лицензию", "extend": "Продлить лицензию"}[action]
    await message.answer(f"{description}: {parts[1]}" + (f", дней: {parts[2]}" if count == 3 else "") + "? Подтверждение действует 5 минут.",
                         reply_markup=keyboard([[("Подтвердить", "admin_confirm"), ("Отмена", "admin_cancel")]]))

@dp.callback_query(AdminForm.confirm, F.data == "admin_cancel")
async def admin_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(call, "Операция отменена.")

@dp.callback_query(AdminForm.confirm, F.data == "admin_confirm")
async def admin_confirm(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    if time.time() > data.get("expires", 0):
        await show(call, "Подтверждение истекло. Начните операцию заново.")
        return
    action, target = data["action"], data["target"]
    actor = call.from_user.id
    try:
        if action == 'issue_plan':
            result=await api('POST','/v1/admin/licenses/from-plan',{'actor_telegram_id':actor,'target_telegram_id':target,'plan_id':data['plan_id'],'request_id':data['request_id']})
            await show(call,f"Тестовый ключ для ID {target}, лицензия №{result['id']}:\n<code>{escape(result['key'])}</code>\nКлюч показывается один раз. Оплата не проводилась.")
        elif action == "plan":
            result = await api("POST", "/v1/admin/plans", {**data["plan"], "actor_telegram_id": actor, "request_id": data["request_id"]})
            await show(call, f"Тариф {escape(result['name'])} создан. Провайдер оплаты не подключён.")
        elif action == "issue":
            result = await api("POST", "/v1/admin/licenses", {"actor_telegram_id": actor, "target_telegram_id": target, "duration_days": data["days"], "request_id": data["request_id"]})
            await show(call, f"Тестовый ключ для ID {result['target_telegram_id']}, лицензия №{result['id']}:\n<code>{escape(result['key'])}</code>\nКлюч показывается один раз. Передавай только владельцу.")
        elif action == "revoke":
            result = await api("POST", f"/v1/admin/licenses/{target}/revoke", {"actor_telegram_id": actor})
            await show(call, f"Тестовая лицензия №{result['id']}: {result['status']}.")
        else:
            result = await api("POST", f"/v1/admin/licenses/{target}/extend", {"actor_telegram_id": actor, "days": data["days"], "request_id": data["request_id"]})
            await show(call, f"Тестовая лицензия №{result['id']} продлена до {escape(str(result['expires_at']))}.")
    except ApiError:
        await show(call, "Не удалось подтвердить результат операции. Проверь права и состояние на сервере до повтора.")

@dp.callback_query(F.data.startswith('au:'))
async def admin_user_view(call:CallbackQuery):
    uid=call.data.split(':',1)[1]
    if not uid.isdigit(): return await call.answer('Некорректный ID',show_alert=True)
    try:
        user=await api('GET',f'/v1/admin/users/{uid}')
        role=user['role']; disabled=user['disabled']
        rows=[[('🔑 Лицензии',f'aul:{uid}'),('📱 Устройства',f'aud:{uid}')],
              [('Включить' if disabled else 'Отключить',f'ausa:{uid}:{0 if disabled else 1}')],
              [('Сделать пользователем' if role=='admin' else 'Назначить админом',f'aura:{uid}:{"user" if role=="admin" else "admin"}')],
              [('◀️ Пользователи','admin_users')]]
        await show(call,f"👤 <b>ПОЛЬЗОВАТЕЛЬ</b>\n\nID: {uid}\nИмя: {escape(str(user['username'] or 'нет'))}\nРоль: {escape(role)}\nЗаблокирован: {'да' if disabled else 'нет'}",keyboard(rows))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data.startswith('aul:'))
async def admin_user_licenses(call:CallbackQuery):
    uid=call.data.split(':',1)[1]
    if not uid.isdigit(): return await call.answer('Некорректный ID',show_alert=True)
    try:
        grants=(await api('GET',f'/v1/admin/users/{uid}/licenses'))['licenses']
        lines=[f"№{g['id']} · {escape(g['status'])} · {escape(str(g['expires_at'] or 'не активирована'))}" for g in grants[:30]]
        await show(call,'🔑 <b>ЛИЦЕНЗИИ</b>\n\n'+('\n'.join(lines) if lines else 'Лицензий нет.')+'\n\n/revoke ID и /extend ID ДНЕЙ',keyboard([[('◀️ Пользователь',f'au:{uid}')]]))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data.startswith('aud:'))
async def admin_user_devices(call:CallbackQuery):
    uid=call.data.split(':',1)[1]
    if not uid.isdigit(): return await call.answer('Некорректный ID',show_alert=True)
    try:
        devices=(await api('GET',f'/v1/admin/users/{uid}/devices'))['devices']
        lines=[f"{escape(d['name'][:25])} · {escape(d['platform'])} · {escape(d['status'])}" for d in devices[:20]]
        rows=[[(f"Отозвать {d['name'][:20]}",f"adask:{uid}:{d['id']}")] for d in devices[:20] if d['status'] in ('pending','active')]
        rows.append([('◀️ Пользователь',f'au:{uid}')])
        await show(call,'📱 <b>УСТРОЙСТВА</b>\n\n'+('\n'.join(lines) if lines else 'Устройств нет.'),keyboard(rows))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data.startswith('ausa:') | F.data.startswith('aura:') | F.data.startswith('adask:'))
async def admin_change_ask(call:CallbackQuery):
    parts=call.data.split(':')
    if len(parts)!=3 or not parts[1].isdigit(): return await call.answer('Некорректная кнопка',show_alert=True)
    prefix={'ausa':'aus','aura':'aur','adask':'adr'}[parts[0]]
    await show(call,'Подтвердить изменение? Права проверяются сервером.',keyboard([[('Подтвердить',f'{prefix}:{parts[1]}:{parts[2]}'),('Отмена',f'au:{parts[1]}')]]))

@dp.callback_query(F.data.startswith('aus:') | F.data.startswith('aur:') | F.data.startswith('adr:'))
async def admin_change_confirm(call:CallbackQuery):
    parts=call.data.split(':')
    if len(parts)!=3 or not parts[1].isdigit(): return await call.answer('Некорректная кнопка',show_alert=True)
    kind,uid,value=parts
    try:
        if kind=='aus' and value in ('0','1'):
            await api('POST',f'/v1/admin/users/{uid}/disabled',{'disabled':value=='1'})
        elif kind=='aur' and value in ('admin','user'):
            await api('POST',f'/v1/admin/users/{uid}/role',{'role':value})
        elif kind=='adr' and len(value)==36:
            await api('POST',f'/v1/admin/users/{uid}/devices/{value}/revoke')
        else: return await call.answer('Некорректная кнопка',show_alert=True)
        await show(call,'Изменение сохранено.',keyboard([[('◀️ Пользователь',f'au:{uid}')]]))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data.startswith('ap:'))
async def admin_plan_view(call:CallbackQuery):
    pid=call.data.split(':',1)[1]
    try:
        plans=(await api('GET','/v1/admin/plans'))['plans']
        p=next((x for x in plans if x['id']==pid),None)
        if not p: return await call.answer('Тариф не найден',show_alert=True)
        flag='0' if p['enabled'] else '1'
        text=f"💎 <b>{escape(p['name'])}</b>\nID: <code>{pid}</code>\n{p['duration_days']} дней · {p['device_limit']} устройств · {escape(p['platform'])}\nЦена: {p['price_minor']} {escape(p['currency'])} (мин. ед.)\nСоздание лицензии: /grantplan ID ID_ТАРИФА"
        await show(call,text,keyboard([[('Выключить' if p['enabled'] else 'Включить',f'apa:{pid}:{flag}')],[('◀️ Тарифы','admin_plans')]]))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data.startswith('apa:'))
async def admin_plan_toggle_ask(call:CallbackQuery):
    parts=call.data.split(':')
    if len(parts)!=3 or len(parts[1])!=36 or parts[2] not in ('0','1'): return await call.answer('Некорректная кнопка',show_alert=True)
    await show(call,'Изменить доступность тарифа? Существующие права лицензий не меняются.',keyboard([[('Подтвердить',f'apt:{parts[1]}:{parts[2]}'),('Отмена',f'ap:{parts[1]}')]]))

@dp.callback_query(F.data.startswith('apt:'))
async def admin_plan_toggle(call:CallbackQuery):
    parts=call.data.split(':')
    if len(parts)!=3 or len(parts[1])!=36 or parts[2] not in ('0','1'): return await call.answer('Некорректная кнопка',show_alert=True)
    try:
        await api('POST',f'/v1/admin/plans/{parts[1]}/enabled',{'enabled':parts[2]=='1'})
        await show(call,'Доступность тарифа изменена.',keyboard([[('◀️ Тарифы','admin_plans')]]))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data == "devices")
async def devices(call: CallbackQuery):
    try:
        result=await api("GET",f"/v1/users/{call.from_user.id}/devices")
        entries=result['devices']
        rows=[[(f"{item['name'][:24]} · {item['status']}",f"device_view:{item['id']}")] for item in entries[:20]]
        rows.append([("◀️ Главное меню", "home")])
        await show(call,"📱 <b>МОИ УСТРОЙСТВА</b>\n\n" + ("Выбери устройство. Статус active не означает подключение к игре." if entries else "Устройств нет."),keyboard(rows))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data.startswith("device_view:"))
async def device_view(call: CallbackQuery):
    ident=call.data.split(":",1)[1]
    try:
        entries=(await api("GET",f"/v1/users/{call.from_user.id}/devices"))['devices']
        item=next((v for v in entries if v['id']==ident),None)
        if not item: return await call.answer("Устройство не найдено",show_alert=True)
        text=f"📱 <b>{escape(item['name'])}</b>\nПлатформа: {escape(item['platform'])}\nСтатус: {escape(item['status'])}\nПоследняя активность: {escape(str(item['last_seen_at'] or 'нет'))}"
        rows=[]
        if item['status'] in {'pending','active'}: rows.append([("Отключить",f"device_revoke_ask:{ident}")])
        rows.append([("◀️ Назад","devices")])
        await show(call,text,keyboard(rows))
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data.startswith("device_revoke_ask:"))
async def device_revoke_ask(call: CallbackQuery):
    ident=call.data.split(":",1)[1]
    if len(ident)!=36: return await call.answer("Некорректное устройство",show_alert=True)
    await show(call,"Отозвать устройство на сервере?",keyboard([[("Отозвать",f"device_revoke:{ident}"),("Отмена",f"device_view:{ident}")]]))

@dp.callback_query(F.data.startswith("device_revoke:"))
async def device_revoke(call: CallbackQuery):
    ident=call.data.split(":",1)[1]
    if len(ident)!=36: return await call.answer("Некорректное устройство",show_alert=True)
    try:
        await api("POST",f"/v1/users/{call.from_user.id}/devices/{ident}/revoke")
        await show(call,"Устройство отозвано сервером. Его секрет больше не даёт доступ к API.")
    except ApiError as exc: await fail(call,exc)

@dp.callback_query(F.data == "help")
async def help_page(call: CallbackQuery):
    await show(call, "📚 <b>ИНСТРУКЦИЯ</b>\n\nЭто локальный тестовый проект. Игровой плагин, привязка и реальные уведомления пока не подключены.")

@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(call, "🛟 <b>ПОДДЕРЖКА</b>\n\nТекстовые обращения сохраняются в тестовой базе. Ответы доступны в разделе «Мои обращения». Уведомление возможно при запущенном worker и включённых системных уведомлениях хотя бы на одной платформе; вложения ещё не подключены.", keyboard([
        [("Создать обращение", "ticket_new")], [("Мои обращения", "ticket_list")], [("◀️ Главное меню", "home")]]))

@dp.callback_query(F.data == "ticket_new")
async def ticket_new(call: CallbackQuery):
    await show(call, "Выбери категорию обращения:", keyboard([[("Подключение", "ticket_cat:connection")], [("Лицензия", "ticket_cat:license")], [("Другое", "ticket_cat:other")], [("◀️ Назад", "support")]]))

@dp.callback_query(F.data.in_({"ticket_cat:connection", "ticket_cat:license", "ticket_cat:other"}))
async def ticket_category(call: CallbackQuery, state: FSMContext):
    await state.set_state(SupportForm.waiting_for_message)
    await state.update_data(category=call.data.split(":", 1)[1], request_id=str(uuid4()))
    await show(call, "Напиши текст обращения (до 2000 символов). Не отправляй пароли и токены. Для отмены — /cancel.", keyboard([[("◀️ Отмена", "home")]]))

@dp.message(SupportForm.waiting_for_message, F.text)
async def ticket_message(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text or len(text) > 2000:
        await message.answer("Введите от 1 до 2000 символов или /cancel.")
        return
    data = await state.get_data()
    if data.get("pending_text") and data["pending_text"] != text:
        await message.answer("Повтори прежний текст, чтобы проверить результат, или нажми /cancel.")
        return
    await state.update_data(pending_text=text)
    try:
        result = await api("POST", f"/v1/users/{message.from_user.id}/tickets", {"category": data["category"], "message": text, "request_id": data["request_id"]})
        await state.clear()
        await message.answer(f"Обращение №{result['id']} сохранено. Проверяй ответ в разделе «Мои обращения».", reply_markup=main_keyboard())
    except ApiError:
        await message.answer("Не удалось подтвердить сохранение. Проверь список обращений перед повтором или /cancel.")

@dp.callback_query(F.data == "ticket_list")
async def ticket_list(call: CallbackQuery):
    try:
        data = await api("GET", f"/v1/users/{call.from_user.id}/tickets")
        tickets = data["tickets"]
        rows = [[(f"№{r['id']} — {r['status']}", f"ticket_view:{r['id']}")] for r in tickets]
        rows.append([("◀️ Назад", "support")])
        await show(call, "🛟 <b>МОИ ОБРАЩЕНИЯ</b>\n\n" + ("Выбери обращение." if tickets else "Обращений пока нет."), keyboard(rows))
    except ApiError as exc:
        await fail(call, exc)

def support_text(ticket):
    # Bound rendered content to fit Telegram's message size limit. Full data stays in API.
    lines = [f"🛟 <b>ОБРАЩЕНИЕ №{ticket['id']}</b>", f"Статус: {escape(ticket['status'])}",
             "Сообщение: " + escape(ticket['initial_message'][:500])]
    if len(ticket['messages']) > 3:
        lines.append("Показаны последние 3 ответа.")
    for item in ticket['messages'][-3:]:
        label = "Поддержка" if item['author_type'] == 'admin' else "Пользователь"
        lines.append(f"{label}: " + escape(item['text'][:500]))
    return "\n\n".join(lines)

@dp.callback_query(F.data.startswith("ticket_view:"))
async def ticket_view(call: CallbackQuery):
    ident = call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    try:
        ticket = await api("GET", f"/v1/users/{call.from_user.id}/tickets/{ident}")
        rows=[]
        if ticket['status'] == 'open':
            rows += [[("Ответить", f"ticket_reply:{ident}"), ("Закрыть", f"ticket_close_ask:{ident}")]]
        rows.append([("◀️ Мои обращения", "ticket_list")])
        await show(call, support_text(ticket), keyboard(rows))
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data.startswith("ticket_reply:"))
async def ticket_reply(call: CallbackQuery, state: FSMContext):
    ident = call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    try:
        await api("GET", f"/v1/users/{call.from_user.id}/tickets/{ident}")
        await state.set_state(SupportForm.waiting_for_reply)
        await state.update_data(ticket_id=int(ident))
        await show(call, "Напиши ответ до 2000 символов. Отмена: /cancel.")
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data.startswith("ticket_close_ask:"))
async def ticket_close_ask(call: CallbackQuery):
    ident = call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    await show(call, f"Закрыть обращение №{ident}?", keyboard([[("Закрыть", f"ticket_close:{ident}"), ("Отмена", f"ticket_view:{ident}")]]))

@dp.callback_query(F.data.startswith("ticket_close:"))
async def ticket_close(call: CallbackQuery):
    ident = call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    try:
        await api("POST", f"/v1/users/{call.from_user.id}/tickets/{ident}/close")
        await show(call, f"Обращение №{ident} закрыто.")
    except ApiError as exc:
        await fail(call, exc)

@dp.message(Command("tickets"))
async def admin_tickets(message: Message):
    try:
        data=await api("GET", f"/v1/admin/tickets?actor_telegram_id={message.from_user.id}")
        rows=[[(f"№{r['id']} — {r['category']}", f"admin_ticket:{r['id']}")] for r in data['tickets']]
        await message.answer("Открытые обращения:" if rows else "Открытых обращений нет.", reply_markup=keyboard(rows) if rows else main_keyboard())
    except ApiError:
        await message.answer("Не удалось получить обращения: проверь права и подключение к API.")

@dp.callback_query(F.data.startswith("admin_ticket:"))
async def admin_ticket(call: CallbackQuery):
    ident=call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    try:
        ticket=await api("GET", f"/v1/admin/tickets/{ident}?actor_telegram_id={call.from_user.id}")
        rows=[]
        if ticket['status']=='open':
            rows.append([("Ответить", f"admin_ticket_reply:{ident}"), ("Закрыть", f"admin_ticket_close_ask:{ident}")])
        rows.append([("Главное меню", "home")])
        await show(call, support_text(ticket)+f"\n\nTelegram ID: <code>{ticket['telegram_id']}</code>", keyboard(rows))
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data.startswith("admin_ticket_reply:"))
async def admin_ticket_reply(call: CallbackQuery, state: FSMContext):
    ident=call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    try:
        await api("GET", f"/v1/admin/tickets/{ident}?actor_telegram_id={call.from_user.id}")
        await state.set_state(SupportForm.waiting_for_admin_reply)
        await state.update_data(ticket_id=int(ident))
        await show(call, "Введи ответ до 2000 символов. Отмена: /cancel.")
    except ApiError as exc:
        await fail(call, exc)

@dp.callback_query(F.data.startswith("admin_ticket_close_ask:"))
async def admin_ticket_close_ask(call: CallbackQuery):
    ident=call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    await show(call, f"Закрыть обращение №{ident}?", keyboard([[("Закрыть", f"admin_ticket_close:{ident}"), ("Отмена", f"admin_ticket:{ident}")]]))

@dp.callback_query(F.data.startswith("admin_ticket_close:"))
async def admin_ticket_close(call: CallbackQuery):
    ident=call.data.split(":", 1)[1]
    if not ident.isdigit():
        return await call.answer("Некорректное обращение", show_alert=True)
    try:
        await api("POST", f"/v1/admin/tickets/{ident}/close", {"actor_telegram_id":call.from_user.id})
        await show(call, f"Обращение №{ident} закрыто.")
    except ApiError as exc:
        await fail(call, exc)

@dp.message(SupportForm.waiting_for_reply, F.text)
@dp.message(SupportForm.waiting_for_admin_reply, F.text)
async def support_reply(message: Message, state: FSMContext):
    text=message.text.strip()
    if not text or len(text)>2000:
        await message.answer("Введите от 1 до 2000 символов или /cancel.")
        return
    data=await state.get_data()
    state_name=await state.get_state()
    is_admin=state_name == SupportForm.waiting_for_admin_reply.state
    if data.get('pending_text') and data['pending_text'] != text:
        await message.answer("Повтори прежний текст, чтобы проверить результат, или нажми /cancel.")
        return
    if not data.get('pending_text'):
        await state.update_data(pending_text=text, request_id=str(uuid4()))
        data=await state.get_data()
    target=data['ticket_id']
    if is_admin:
        path=f"/v1/admin/tickets/{target}/messages"
        body={"text":text,"request_id":data['request_id'],"actor_telegram_id":message.from_user.id}
    else:
        path=f"/v1/users/{message.from_user.id}/tickets/{target}/messages"
        body={"text":text,"request_id":data['request_id']}
    try:
        await api("POST",path,body)
        await state.clear()
        await message.answer("Ответ сохранён. Уведомление о ответе администратора ставится в очередь, если системные уведомления включены; доставка не гарантирована.",reply_markup=main_keyboard())
    except ApiError:
        await message.answer("Не удалось подтвердить сохранение. Для безопасного повтора отправь тот же текст или /cancel.")

async def main():
    if not bot:
        raise RuntimeError("Set a TEST BOT_TOKEN in .env")
    parsed = urlparse(settings.api_base_url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise RuntimeError("API_BASE_URL must use HTTPS except on localhost")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
