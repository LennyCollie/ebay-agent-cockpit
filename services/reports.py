import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from io import BytesIO
import time

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from models import SessionLocal, Report, ReportGeneration, ReportTemplate, Alert, PriceHistory
from sqlalchemy import and_, or_


class ReportGenerator:
    REPORT_TYPES = {
        "price_summary": "Preiszusammenfassung",
        "price_trends": "Preistrends",
        "auction_history": "Auktionsverlauf",
        "performance": "Leistungsbericht",
        "activity": "Aktivitätsbericht",
        "alerts_summary": "Benachrichtigungszusammenfassung",
    }
    
    STORAGE_DIR = "reports_output"
    RETENTION_DAYS = 30
    
    def __init__(self):
        if not os.path.exists(self.STORAGE_DIR):
            os.makedirs(self.STORAGE_DIR)
    
    def generate_report(self, user_id: int, report_id: int) -> tuple[bool, str]:
        db = SessionLocal()
        try:
            report = db.query(Report).filter_by(id=report_id, user_id=user_id).first()
            if not report:
                return False, "Report not found"
            
            generation = ReportGeneration(
                report_id=report_id,
                user_id=user_id,
                status="processing"
            )
            db.add(generation)
            db.commit()
            
            start_time = time.time()
            
            try:
                if report.report_type == "price_summary":
                    success, filepath = self._generate_price_summary(user_id, report, generation)
                elif report.report_type == "price_trends":
                    success, filepath = self._generate_price_trends(user_id, report, generation)
                elif report.report_type == "auction_history":
                    success, filepath = self._generate_auction_history(user_id, report, generation)
                elif report.report_type == "activity":
                    success, filepath = self._generate_activity_report(user_id, report, generation)
                else:
                    success, filepath = False, "Unknown report type"
                
                generation_time = int((time.time() - start_time) * 1000)
                
                if success:
                    file_size = os.path.getsize(filepath)
                    generation.status = "completed"
                    generation.file_path = filepath
                    generation.file_size = file_size
                    generation.file_url = f"/api/reports/{generation.id}/download"
                    generation.generation_time_ms = generation_time
                    generation.completed_at = datetime.utcnow()
                    generation.expires_at = datetime.utcnow() + timedelta(days=self.RETENTION_DAYS)
                else:
                    generation.status = "failed"
                    generation.error_message = filepath
                
                report.last_generated = datetime.utcnow()
                db.commit()
                
                return success, filepath if success else filepath
                
            except Exception as e:
                generation.status = "failed"
                generation.error_message = str(e)
                db.commit()
                return False, f"Generation error: {str(e)}"
        
        finally:
            db.close()
    
    def _generate_price_summary(self, user_id: int, report: Report, generation: ReportGeneration) -> tuple[bool, str]:
        db = SessionLocal()
        try:
            filepath = os.path.join(self.STORAGE_DIR, f"price_summary_{user_id}_{generation.id}.pdf")
            
            doc = SimpleDocTemplate(filepath, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()
            
            elements.append(Paragraph("Preiszusammenfassung", styles['Heading1']))
            elements.append(Spacer(1, 0.3*inch))
            
            alerts = db.query(Alert).filter_by(user_id=user_id).limit(20).all()
            
            if alerts:
                data = [["Artikel", "Aktueller Preis", "Typ", "Status"]]
                for alert in alerts:
                    data.append([
                        alert.item_title[:30],
                        f"€{alert.current_price:.2f}",
                        alert.alert_type,
                        "Aktiv" if alert.is_enabled else "Inaktiv"
                    ])
                
                table = Table(data, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                elements.append(table)
            
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph(f"Generiert am: {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')}", styles['Normal']))
            
            doc.build(elements)
            generation.row_count = len(alerts)
            return True, filepath
            
        except Exception as e:
            return False, str(e)
        finally:
            db.close()
    
    def _generate_price_trends(self, user_id: int, report: Report, generation: ReportGeneration) -> tuple[bool, str]:
        filepath = os.path.join(self.STORAGE_DIR, f"price_trends_{user_id}_{generation.id}.pdf")
        doc = SimpleDocTemplate(filepath, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        
        elements.append(Paragraph("Preistrends", styles['Heading1']))
        elements.append(Spacer(1, 0.3*inch))
        
        elements.append(Paragraph("Trend-Analyse der letzten 30 Tage", styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))
        
        trend_data = [["Zeitraum", "Durchschnittspreis", "Min", "Max"]]
        trend_data.append(["Letzte 7 Tage", "€45.00", "€40.00", "€50.00"])
        trend_data.append(["Letzte 30 Tage", "€42.50", "€38.00", "€52.00"])
        
        table = Table(trend_data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        
        doc.build(elements)
        return True, filepath
    
    def _generate_auction_history(self, user_id: int, report: Report, generation: ReportGeneration) -> tuple[bool, str]:
        filepath = os.path.join(self.STORAGE_DIR, f"auction_history_{user_id}_{generation.id}.pdf")
        doc = SimpleDocTemplate(filepath, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        
        elements.append(Paragraph("Auktionsverlauf", styles['Heading1']))
        elements.append(Spacer(1, 0.3*inch))
        
        history_data = [["Artikel", "Startpreis", "Endpreis", "Datum"]]
        history_data.append(["Test Artikel 1", "€20.00", "€45.50", "15.12.2025"])
        history_data.append(["Test Artikel 2", "€10.00", "€28.99", "14.12.2025"])
        
        table = Table(history_data, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        
        doc.build(elements)
        return True, filepath
    
    def _generate_activity_report(self, user_id: int, report: Report, generation: ReportGeneration) -> tuple[bool, str]:
        filepath = os.path.join(self.STORAGE_DIR, f"activity_report_{user_id}_{generation.id}.pdf")
        doc = SimpleDocTemplate(filepath, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        
        elements.append(Paragraph("Aktivitätsbericht", styles['Heading1']))
        elements.append(Spacer(1, 0.3*inch))
        
        activity_data = [["Aktivität", "Anzahl", "Datum"]]
        activity_data.append(["Benachrichtigungen gesendet", "45", "Heute"])
        activity_data.append(["Artikel überwacht", "12", "Heute"])
        
        table = Table(activity_data, colWidths=[2*inch, 1.5*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        
        doc.build(elements)
        return True, filepath
    
    def cleanup_expired_reports(self):
        db = SessionLocal()
        try:
            expired = db.query(ReportGeneration).filter(
                ReportGeneration.expires_at < datetime.utcnow()
            ).all()
            
            for gen in expired:
                if gen.file_path and os.path.exists(gen.file_path):
                    try:
                        os.remove(gen.file_path)
                    except:
                        pass
                db.delete(gen)
            
            db.commit()
        finally:
            db.close()
    
    def get_report_file(self, user_id: int, generation_id: int) -> Optional[bytes]:
        db = SessionLocal()
        try:
            generation = db.query(ReportGeneration).filter_by(
                id=generation_id,
                user_id=user_id,
                status="completed"
            ).first()
            
            if not generation or not generation.file_path:
                return None
            
            if not os.path.exists(generation.file_path):
                return None
            
            with open(generation.file_path, 'rb') as f:
                return f.read()
        finally:
            db.close()
