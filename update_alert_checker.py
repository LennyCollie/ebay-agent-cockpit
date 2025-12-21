import os

with open("alert_checker.py", "r") as f:
    content = f.read()

content = content.replace(
    '''def send_telegram_alert(
    chat_id: str,
    item: Dict,
    agent_name: str,
    source: str = "ebay",
) -> bool:''',
    '''def send_telegram_alert(
    chat_id: str,
    item: Dict,
    agent_name: str,
    source: str = "ebay",
    alert_id: int = None,
) -> bool:'''
)

content = content.replace(
    '''        success = send_new_item_alert(
            chat_id=chat_id,
            item=formatted_item,
            agent_name=agent_name,
            with_image=bool(formatted_item["image_url"]),
        )''',
    '''        success = send_new_item_alert(
            chat_id=chat_id,
            item=formatted_item,
            agent_name=agent_name,
            alert_id=alert_id,
            with_image=bool(formatted_item["image_url"]),
        )'''
)

content = content.replace(
    '''        for item in new_items[:5]:
            success = send_telegram_alert(
                str(telegram_chat_id),
                item,
                agent_name,
                source,
            )''',
    '''        for item in new_items[:5]:
            success = send_telegram_alert(
                str(telegram_chat_id),
                item,
                agent_name,
                source,
                alert_id,
            )'''
)

with open("alert_checker.py", "w") as f:
    f.write(content)

print("✅ alert_checker.py updated successfully")
