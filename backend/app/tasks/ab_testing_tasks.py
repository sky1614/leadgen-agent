import logging
from ..tasks.celery_app import celery

logger = logging.getLogger("ab_testing_tasks")


@celery.task
def start_weekly_ab_tests():
    from ..database import SessionLocal
    from ..models import ClientDB, CampaignDB

    db = SessionLocal()
    tests_started = 0
    skipped = 0
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        for client in clients:
            try:
                camps = db.query(CampaignDB).filter(
                    CampaignDB.client_id == client.id,
                    CampaignDB.status == "active",
                ).all()
                for camp in camps:
                    try:
                        from ..services.ab_testing_service import maybe_start_ab_test
                        template_name = camp.target_industry or "generic"
                        test_id = maybe_start_ab_test(client.id, camp.id, template_name, db)
                        if test_id:
                            tests_started += 1
                        else:
                            skipped += 1
                    except Exception as e:
                        logger.error(f"ab test start error camp={camp.id}: {e}")
                        skipped += 1
            except Exception as e:
                logger.error(f"ab test client error client={client.id}: {e}")
    finally:
        db.close()

    logger.info(f"start_weekly_ab_tests: started={tests_started} skipped={skipped}")
    return {"tests_started": tests_started, "skipped": skipped}


@celery.task
def check_all_running_tests():
    from ..database import SessionLocal
    from ..models import ABTestDB
    from ..services.ab_testing_service import check_significance

    db = SessionLocal()
    checked = 0
    concluded = 0
    try:
        tests = db.query(ABTestDB).filter(ABTestDB.status == "running").all()
        for test in tests:
            try:
                before = test.status
                check_significance(test.id, db)
                db.refresh(test)
                checked += 1
                if test.status == "completed":
                    concluded += 1
            except Exception as e:
                logger.error(f"check significance error test={test.id}: {e}")
    finally:
        db.close()

    logger.info(f"check_all_running_tests: checked={checked} concluded={concluded}")
    return {"checked": checked, "concluded": concluded}
