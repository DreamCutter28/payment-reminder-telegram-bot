import os
from dotenv import load_dotenv
import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import datetime
import time
import threading
import logging
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, func, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Получение токена бота и ID администратора из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

bot = telebot.TeleBot(BOT_TOKEN)

# Настройка базы данных
Base = declarative_base()
engine = create_engine('sqlite:///users.db')
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String)
    payments = relationship("Payment", back_populates="user")

class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    payment_date = Column(DateTime, default=datetime.datetime.utcnow)
    amount = Column(Integer)
    confirmed = Column(Boolean, default=False)
    rejected = Column(Boolean, default=False)
    comment = Column(String)
    month = Column(String)
    user = relationship("User", back_populates="payments")

# Создание таблиц
Base.metadata.create_all(engine)

def add_user(user_id, username):
    session = Session()
    user = session.query(User).filter_by(id=user_id).first()
    if not user:
        user = User(id=user_id, username=username)
        session.add(user)
    else:
        user.username = username
    session.commit()
    session.close()

def get_all_users():
    session = Session()
    users = session.query(User).all()
    session.close()
    return [(user.id, user.username) for user in users]

def remove_user(user_id):
    session = Session()
    user = session.query(User).filter_by(id=user_id).first()
    if user:
        session.delete(user)
        session.commit()
    session.close()

def add_payment(user_id, total_amount, months):
    session = Session()
    payments = []
    amount_per_month = total_amount // len(months)
    for month in months:
        payment = Payment(user_id=user_id, amount=amount_per_month, confirmed=False, month=month)
        session.add(payment)
        payments.append(payment)
    session.commit()
    payment_ids = [payment.id for payment in payments]
    session.close()
    return payment_ids

def confirm_payment(payment_id):
    session = Session()
    payment = session.query(Payment).filter_by(id=payment_id).first()
    if payment:
        payment.confirmed = True
        session.commit()
    session.close()

def reject_payment(payment_id, comment):
    session = Session()
    payment = session.query(Payment).filter_by(id=payment_id).first()
    if payment:
        payment.rejected = True
        payment.comment = comment
        session.commit()
        user_id = payment.user_id
    session.close()
    return user_id if payment else None

def get_payments_by_month():
    session = Session()
    payments = session.query(User.username, 
                             Payment.month,
                             func.count('*').label('count'))\
                      .join(Payment)\
                      .filter(Payment.confirmed == True)\
                      .group_by(User.id, Payment.month)\
                      .order_by(Payment.month.desc(), User.username)\
                      .all()
    session.close()
    return [(p.username, p.month, p.count) for p in payments]

def get_last_payment(user_id):
    session = Session()
    last_payment = session.query(Payment)\
                          .filter_by(user_id=user_id, confirmed=True)\
                          .order_by(Payment.payment_date.desc())\
                          .first()
    session.close()
    return last_payment

def is_payment_confirmed_for_month(user_id, month):
    session = Session()
    payment = session.query(Payment)\
                     .filter_by(user_id=user_id, month=month, confirmed=True)\
                     .first()
    session.close()
    return payment is not None

def is_payment_exists_for_month(user_id, month):
    session = Session()
    payment = session.query(Payment)\
                     .filter_by(user_id=user_id, month=month)\
                     .filter((Payment.confirmed == True) | ((Payment.confirmed == False) & (Payment.rejected == False)))\
                     .first()
    session.close()
    return payment is not None

def get_user_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("📊 Статус"), KeyboardButton("💰 Оплатить"))
    keyboard.add(KeyboardButton("👨‍💼 Админ-панель"))
    return keyboard

def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("👥 Список пользователей"), KeyboardButton("📈 Статистика оплат"))
    keyboard.add(KeyboardButton("📢 Отправить уведомление"), KeyboardButton("✅ Подтвердить оплаты"))
    keyboard.add(KeyboardButton("❌ Удалить оплаты"), KeyboardButton("🔍 Неоплатившие пользователи"))
    keyboard.add(KeyboardButton("👤 Пользовательская панель"))
    return keyboard

def get_last_paid_month(user_id):
    session = Session()
    last_payment = session.query(Payment)\
                          .filter_by(user_id=user_id, confirmed=True)\
                          .order_by(Payment.month.desc())\
                          .first()
    session.close()
    if last_payment:
        return datetime.datetime.strptime(last_payment.month, '%Y-%m')
    return None

def delete_payment(payment_id):
    session = Session()
    payment = session.query(Payment).filter_by(id=payment_id).first()
    if payment:
        session.delete(payment)
        session.commit()
    session.close()

@bot.message_handler(commands=['start'])
def start(message):
    add_user(message.from_user.id, message.from_user.username)
    bot.reply_to(message, "Привет! Я буду напоминать вам об оплате каждое первое число месяца.", reply_markup=get_user_keyboard())
    logger.info(f"Новый пользователь: {message.from_user.username} (ID: {message.from_user.id})")

@bot.message_handler(func=lambda message: message.text == "📊 Статус")
def status_command(message):
    user_id = message.from_user.id
    last_payment = get_last_payment(user_id)
    if last_payment:
        status_text = f"Ваша последняя подтвержденная оплата была {last_payment.payment_date.strftime('%Y-%m-%d %H:%M:%S')} за месяц {last_payment.month}."
    else:
        status_text = "У вас еще нет подтвержденных оплат."
    bot.reply_to(message, status_text)

@bot.message_handler(func=lambda message: message.text == "💰 Оплатить")
def pay_command(message):
    user_id = message.from_user.id
    last_paid_month = get_last_paid_month(user_id)
    
    if last_paid_month:
        start_date = last_paid_month + datetime.timedelta(days=32)
        start_date = start_date.replace(day=1)
    else:
        start_date = datetime.datetime.now().replace(day=1)
    
    markup = InlineKeyboardMarkup()
    for i in range(1, 13):  # Предлагаем от 1 до 12 месяцев
        end_date = (start_date + datetime.timedelta(days=32*i)).replace(day=1) - datetime.timedelta(days=1)
        period = f"{start_date.strftime('%d.%m.%Y')}-{end_date.strftime('%d.%m.%Y')}"
        markup.add(InlineKeyboardButton(f"{i} месяц(ев) ({period})", callback_data=f"pay_{i}_{start_date.strftime('%Y-%m')}"))
    
    if last_paid_month:
        bot.send_message(message.chat.id, f"Ваша текущая подписка оплачена до {last_paid_month.strftime('%d.%m.%Y')}. Выберите период для продления:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Выберите количество месяцев для оплаты:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def handle_pay_selection(call):
    _, num_months, start_month = call.data.split('_')
    num_months = int(num_months)
    amount = num_months * 100  # 100 RUB за месяц
    
    start_date = datetime.datetime.strptime(start_month, '%Y-%m')
    months = []
    for i in range(num_months):
        current_date = start_date + datetime.timedelta(days=32*i)
        current_date = current_date.replace(day=1)
        end_date = (current_date + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
        months.append((current_date.strftime('%Y-%m'), f"{current_date.strftime('%d.%m.%Y')}-{end_date.strftime('%d.%m.%Y')}"))
    
    # Проверяем, есть ли уже оплата за выбранные месяцы
    already_paid_months = [month for month, _ in months if is_payment_exists_for_month(call.from_user.id, month)]
    
    if already_paid_months:
        bot.answer_callback_query(call.id, f"У вас уже есть оплата за следующие месяцы: {', '.join(already_paid_months)}. Выберите другой период.", show_alert=True)
        return
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Оплатил", callback_data=f"paid_{call.from_user.id}_{amount}_{','.join([m for m, _ in months])}"))
    
    periods = ', '.join([period for _, period in months])
    bot.edit_message_text(f"Сумма к оплате: {amount} RUB за периоды: {periods}\nНажмите кнопку после оплаты:",
                          call.message.chat.id,
                          call.message.message_id,
                          reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "👨‍💼 Админ-панель")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "У вас нет доступа к админ-панели.")
        return
    
    bot.send_message(message.chat.id, "Админ-панель:", reply_markup=get_admin_keyboard())

@bot.message_handler(func=lambda message: message.text == "👤 Пользовательская панель")
def user_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "У вас нет доступа к этой функции.")
        return
    
    bot.send_message(message.chat.id, "Пользовательская панель:", reply_markup=get_user_keyboard())

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and message.text == "👥 Список пользователей")
def admin_users_list(message):
    users = get_all_users()
    user_list = "\n".join([f"{user[1]} (ID: {user[0]})" for user in users])
    bot.reply_to(message, f"Список пользователей:\n\n{user_list}")

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and message.text == "📈 Статистика оплат")
def admin_payments_stats(message):
    session = Session()
    payments = session.query(Payment, User)\
                      .join(User)\
                      .filter(Payment.confirmed == True)\
                      .order_by(User.username, Payment.payment_date)\
                      .all()
    session.close()

    stats = {}
    for payment, user in payments:
        if user.username not in stats:
            stats[user.username] = []
        stats[user.username].append({
            'date': payment.payment_date,
            'month': payment.month,
            'amount': payment.amount
        })

    response = "Статистика подтвержденных оплат:\n\n"
    for username, user_payments in stats.items():
        response += f"{username}:\n"
        for payment in user_payments:
            response += f" - {payment['date'].strftime('%d.%m.%Y')}: {payment['month']} ({payment['amount']} RUB)\n"
        response += "\n"

    bot.reply_to(message, response)

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and message.text == "📢 Отправить уведомление")
def admin_send_notification(message):
    msg = bot.reply_to(message, "Введите текст уведомления для отправки всем пользователям:")
    bot.register_next_step_handler(msg, process_notification_text)

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and message.text == "✅ Подтвердить оплаты")
def admin_confirm_payments(message):
    confirm_payments_menu(message)

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and message.text == "❌ Удалить оплаты")
def admin_delete_payments(message):
    session = Session()
    payments = session.query(Payment, User)\
                      .join(User)\
                      .order_by(User.username, Payment.month)\
                      .all()
    session.close()

    if not payments:
        bot.reply_to(message, "Нет оплат для удаления.")
        return

    markup = InlineKeyboardMarkup()
    for payment, user in payments:
        button_text = f"{user.username} - {payment.month} ({payment.amount} RUB)"
        markup.add(InlineKeyboardButton(button_text, callback_data=f"delete_payment_{payment.id}"))

    bot.reply_to(message, "Выберите оплату для удаления:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_payment_'))
def delete_specific_payment(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "У вас нет доступа к этой функции.")
        return

    payment_id = int(call.data.split('_')[2])
    delete_payment(payment_id)
    bot.answer_callback_query(call.id, "Оплата удалена.")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "Оплата успешно удалена.")

def process_notification_text(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    notification_text = message.text
    send_notification_to_all(notification_text)
    bot.reply_to(message, "Уведомление отправлено всем пользователям.")

def send_notification_to_all(message):
    users = get_all_users()
    for user_id, username in users:
        try:
            bot.send_message(user_id, message)
            logger.info(f"Уведомление отправлено пользователю {username} (ID: {user_id})")
        except ApiTelegramException as e:
            logger.error(f"Ошибка отправки уведомления пользователю {username} (ID: {user_id}): {e}")

def send_reminders():
    current_date = datetime.datetime.now()
    current_month = current_date.strftime('%Y-%m')
    logger.info(f"Проверка напоминаний: {current_date}")
    if current_date.day == 1:
        for user_id, username in get_all_users():
            if not is_payment_confirmed_for_month(user_id, current_month):
                try:
                    markup = InlineKeyboardMarkup()
                    markup.row(InlineKeyboardButton("Оплатить", callback_data=f"pay_1_{current_month}"))
                    bot.send_message(user_id, f"Привет! Напоминаем об оплате за {current_month}.", reply_markup=markup)
                    logger.info(f"Отправлено напоминание пользователю {username} (ID: {user_id})")
                except ApiTelegramException as e:
                    if e.error_code == 403:  # Пользователь заблокировал бота
                        remove_user(user_id)
                        logger.warning(f"Пользователь {username} (ID: {user_id}) удален из-за блокировки бота")

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def handle_payment(call):
    _, user_id, amount, months = call.data.split('_')
    user_id = int(user_id)
    amount = int(amount)
    months = months.split(',')
    
    # Дополнительная проверка перед созданием платежа
    already_paid_months = [month for month in months if is_payment_exists_for_month(user_id, month)]
    if already_paid_months:
        bot.answer_callback_query(call.id, f"Оплата за месяцы {', '.join(already_paid_months)} уже существует. Платеж не создан.", show_alert=True)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        return
    
    payment_ids = add_payment(user_id, amount, months)
    logger.info(f"Получена неподтвержденная оплата от пользователя {call.from_user.username} (ID: {user_id}) за месяцы: {', '.join(months)}")
    bot.answer_callback_query(call.id, "Спасибо за оплату! Администратор проверит и подтвердит её.")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    
    # Уведомляем администратора о новой оплате
    bot.send_message(ADMIN_ID, f"Новая оплата от пользователя {call.from_user.username} (ID: {user_id}) за месяцы: {', '.join(months)}. Используйте команду '✅ Подтвердить оплаты' для подтверждения.")

def confirm_payments_menu(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "У вас нет доступа к этой функции.")
        return

    session = Session()
    unconfirmed_payments = session.query(Payment, User).join(User).filter(Payment.confirmed == False, Payment.rejected == False).all()
    session.close()

    if not unconfirmed_payments:
        bot.reply_to(message, "Нет неподтвержденных оплат.")
        return

    grouped_payments = {}
    for payment, user in unconfirmed_payments:
        key = (user.id, user.username, payment.payment_date)
        if key not in grouped_payments:
            grouped_payments[key] = []
        grouped_payments[key].append(payment)

    for (user_id, username, payment_date), payments in grouped_payments.items():
        total_amount = sum(payment.amount for payment in payments)
        months = ", ".join(payment.month for payment in payments)
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("Подтвердить", callback_data=f"confirm_payment_{'_'.join([str(p.id) for p in payments])}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject_payment_{'_'.join([str(p.id) for p in payments])}")
        )
        bot.send_message(message.chat.id, 
                         f"Оплата от {username} (ID: {user_id})\n"
                         f"Дата: {payment_date}\n"
                         f"Месяцы: {months}\n"
                         f"Общая сумма: {total_amount} RUB", 
                         reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_payment_'))
def confirm_specific_payment(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "У вас нет доступа к этой функции.")
        return

    payment_ids = [int(pid) for pid in call.data.split('_')[2:]]
    for payment_id in payment_ids:
        confirm_payment(payment_id)
    bot.answer_callback_query(call.id, "Оплата подтверждена.")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(call.message.chat.id, "Оплата успешно подтверждена.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_payment_'))
def reject_specific_payment(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "У вас нет доступа к этой функции.")
        return

    payment_ids = [int(pid) for pid in call.data.split('_')[2:]]
    msg = bot.send_message(call.message.chat.id, "Введите комментарий для отклонения платежа:")
    bot.register_next_step_handler(msg, process_reject_comment, payment_ids)

def process_reject_comment(message, payment_ids):
    comment = message.text
    user_id = None
    for payment_id in payment_ids:
        user_id = reject_payment(payment_id, comment)
    if user_id:
        bot.send_message(message.chat.id, "Платеж отклонен.")
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Оплатить снова", callback_data=f"pay_1_{datetime.datetime.now().strftime('%Y-%m')}"))
        bot.send_message(user_id, f"Ваш платеж был отклонен. Комментарий: {comment}", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Ошибка при отклонении платежа.")
        
@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and message.text == "🔍 Неоплатившие пользователи")
def users_without_payment(message):
    current_month = datetime.datetime.now().strftime('%Y-%m')
    session = Session()
    users_with_payment = session.query(User.id).join(Payment).filter(
        Payment.month == current_month,
        Payment.confirmed == True
    ).distinct()
    
    users_without_payment = session.query(User).filter(~User.id.in_(users_with_payment)).all()
    session.close()

    if not users_without_payment:
        bot.reply_to(message, "Все пользователи внесли оплату в текущем месяце.")
    else:
        response = "Пользователи, не внесшие оплату в текущем месяце:\n\n"
        for user in users_without_payment:
            response += f"- {user.username} (ID: {user.id})\n"
        bot.reply_to(message, response)

def main():
    while True:
        try:
            send_reminders()
            time.sleep(3600)  # Проверка каждый час
        except Exception as e:
            logger.error(f"Произошла ошибка: {e}")
            time.sleep(60)  # Подождать минуту перед повторной попыткой

if __name__ == '__main__':
    # Запускаем отправку напоминаний в отдельном потоке
    reminder_thread = threading.Thread(target=main)
    reminder_thread.start()
    
    # Запускаем бота
    logger.info("Бот запущен")
    bot.polling(none_stop=True, interval=0, timeout=20)