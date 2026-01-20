import json
import os
import time
from datetime import datetime
from typing import Optional, Tuple

class GarantDB:
    """База данных для сделок с гарантом"""
    
    def __init__(self):
        self.file_path = "garant_deals.json"
        self.data = self._load_data()
    
    def _load_data(self):
        """Загружаем данные из файла"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_data(self):
        """Сохраняем данные в файл"""
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def create_deal(self, seller_username: str, buyer_username: str, amount: str, 
                   initiator_id: int, chat_id: int, message_id: int) -> dict:
        """Создать новую сделку"""
        deal_id = str(int(time.time()))
        
        deal = {
            "deal_id": deal_id,
            "seller_username": seller_username,
            "buyer_username": buyer_username,
            "amount": amount,
            "status": "pending",  # pending, active, completed, cancelled
            "initiator_id": initiator_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "created_at": datetime.now().isoformat(),
            "admin_notified": False,
            "admin_accepted": False,
            "admin_id": None,
            "completed_at": None,
            "cancelled_at": None,
            "cancelled_reason": None
        }
        
        self.data.append(deal)
        self._save_data()
        return deal
    
    def find_deal(self, deal_id: str) -> Optional[dict]:
        """Найти сделку по ID"""
        for deal in self.data:
            if deal["deal_id"] == deal_id:
                return deal
        return None
    
    def update_deal_status(self, deal_id: str, status: str, admin_id: int = None) -> bool:
        """Обновить статус сделки"""
        for deal in self.data:
            if deal["deal_id"] == deal_id:
                deal["status"] = status
                
                if status == "active" and admin_id:
                    deal["admin_id"] = admin_id
                    deal["admin_accepted"] = True
                elif status == "completed":
                    deal["completed_at"] = datetime.now().isoformat()
                elif status == "cancelled":
                    deal["cancelled_at"] = datetime.now().isoformat()
                
                self._save_data()
                return True
        return False
    
    def set_admin_notified(self, deal_id: str) -> bool:
        """Отметить что админ уведомлен"""
        for deal in self.data:
            if deal["deal_id"] == deal_id:
                deal["admin_notified"] = True
                self._save_data()
                return True
        return False
    
    def get_active_deals(self) -> list:
        """Получить активные сделки"""
        return [deal for deal in self.data if deal["status"] in ["pending", "active"]]
    
    def get_user_deals(self, username: str) -> list:
        """Получить сделки пользователя (как продавца или покупателя)"""
        username = username.lower().replace('@', '')
        user_deals = []
        
        for deal in self.data:
            seller = deal["seller_username"].lower().replace('@', '')
            buyer = deal["buyer_username"].lower().replace('@', '')
            
            if username == seller or username == buyer:
                user_deals.append(deal)
        
        return user_deals
    
    def cleanup_old_deals(self, days: int = 7):
        """Очистить старые завершенные сделки"""
        current_time = datetime.now()
        old_data = []
        
        for deal in self.data:
            if deal["status"] in ["completed", "cancelled"]:
                if "completed_at" in deal and deal["completed_at"]:
                    completed_date = datetime.fromisoformat(deal["completed_at"])
                    if (current_time - completed_date).days > days:
                        continue
                elif "cancelled_at" in deal and deal["cancelled_at"]:
                    cancelled_date = datetime.fromisoformat(deal["cancelled_at"])
                    if (current_time - cancelled_date).days > days:
                        continue
            
            old_data.append(deal)
        
        self.data = old_data
        self._save_data()