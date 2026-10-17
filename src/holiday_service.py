from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
import holidays


class HolidayService:
    """Türkiye resmi tatilleri ve iş günü vade hesaplama servisi."""

    def __init__(self, years_ahead: int = 5):
        current_year = datetime.now().year
        # Geçmiş 2 yıl ve gelecek 5 yılın resmi tatillerini yükle
        years = list(range(current_year - 2, current_year + years_ahead + 1))
        self.tr_holidays = holidays.country_holidays("TR", years=years)

    def is_holiday(self, check_date: date) -> bool:
        """Tarihin resmi tatil olup olmadığını kontrol eder."""
        return check_date in self.tr_holidays

    def get_holiday_name(self, check_date: date) -> Optional[str]:
        """Tarih tatil ise adını döner, değilse None."""
        return self.tr_holidays.get(check_date)

    def is_weekend(self, check_date: date) -> bool:
        """Cumartesi (5) veya Pazar (6) mı kontrol eder."""
        return check_date.weekday() >= 5

    def is_business_day(self, check_date: date) -> bool:
        """Hafta sonu veya resmi tatil olmayan normal iş günü mü?"""
        if self.is_weekend(check_date):
            return False
        if self.is_holiday(check_date):
            return False
        return True

    def calculate_due_date(self, invoice_date: date | str, work_days: int) -> str:
        """
        Fatura kesim tarihinin üzerine tatiller ve haftasonları atlanarak
        belirtilen iş günü kadar gün ekler ve Son Ödeme Tarihi (YYYY-MM-DD) döner.
        """
        result_date, _, _ = self.calculate_due_date_with_breakdown(invoice_date, work_days)
        return result_date.strftime("%Y-%m-%d")

    def calculate_due_date_with_breakdown(
        self, invoice_date: date | str, work_days: int
    ) -> Tuple[date, List[date], List[Tuple[date, str]]]:
        """
        İş günü ekleme hesaplamasını detaylarıyla döner:
        (Sonuç Tarihi, Atlanan Hafta Sonu Günleri, Atlanan Resmi Tatiller [(Tarih, Tatil Adı)])
        """
        if isinstance(invoice_date, str):
            # Farklı formatları parse et
            clean_str = invoice_date.strip()[:10]
            try:
                if "-" in clean_str:
                    curr_date = datetime.strptime(clean_str, "%Y-%m-%d").date()
                elif "." in clean_str:
                    curr_date = datetime.strptime(clean_str, "%d.%m.%Y").date()
                elif "/" in clean_str:
                    curr_date = datetime.strptime(clean_str, "%d/%m/%Y").date()
                else:
                    curr_date = datetime.now().date()
            except Exception:
                curr_date = datetime.now().date()
        else:
            curr_date = invoice_date

        if work_days <= 0:
            return curr_date, [], []

        skipped_weekends: List[date] = []
        skipped_holidays: List[Tuple[date, str]] = []

        added_business_days = 0
        step_date = curr_date

        while added_business_days < work_days:
            step_date += timedelta(days=1)

            if self.is_weekend(step_date):
                skipped_weekends.append(step_date)
                continue

            if self.is_holiday(step_date):
                holiday_name = self.get_holiday_name(step_date) or "Resmi Tatil"
                skipped_holidays.append((step_date, holiday_name))
                continue

            # Geçerli bir iş günü
            added_business_days += 1

        return step_date, skipped_weekends, skipped_holidays

    def get_days_remaining(self, due_date_str: Optional[str]) -> Optional[int]:
        """
        Bugüne göre son ödeme tarihine kalan gün sayısını döner.
        Pozitif: Kalan gün
        0: Bugün son gün
        Negatif: Vadesi geçmiş gün sayısı
        """
        if not due_date_str:
            return None
        try:
            clean_str = str(due_date_str).strip()[:10]
            if "-" in clean_str:
                due_dt = datetime.strptime(clean_str, "%Y-%m-%d").date()
            elif "." in clean_str:
                due_dt = datetime.strptime(clean_str, "%d.%m.%Y").date()
            else:
                return None
            today = datetime.now().date()
            return (due_dt - today).days
        except Exception:
            return None


# Global servis örneği
holiday_service = HolidayService()
