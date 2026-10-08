"""کیبوردهای تعاملی تلگرام برای انتخاب موضوع و تنظیمات ترجمه."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TOPICS = [
    ("🤖 یادگیری ماشین و هوش مصنوعی", "Machine Learning"),
    ("💻 علوم کامپیوتر و برنامه‌نویسی", "Computer Science"),
    ("📐 ریاضیات و فیزیک", "Mathematics & Physics"),
    ("⚡ مهندسی برق و الکترونیک", "Electrical Engineering"),
    ("🧬 علوم پایه و پزشکی", "Biomedical & Natural Sciences"),
    ("🌐 عمومی آکادمیک", "General Academic"),
]


def get_topics_keyboard() -> InlineKeyboardMarkup:
    """ساخت کیبورد شیشه‌ای انتخاب رشته و زمینه درسی."""
    buttons = [
        [InlineKeyboardButton(text=title, callback_data=f"topic:{topic_val}")]
        for title, topic_val in TOPICS
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
