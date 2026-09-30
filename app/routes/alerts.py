from fastapi import APIRouter, HTTPException


def build(alerts, config):
    """Recent WhatsApp alerts and the test message."""
    router = APIRouter()

    @router.get('/api/alerts')
    def list_alerts():
        return alerts.recent(20)

    @router.post('/api/alerts/test', status_code=201)
    def test_alert():
        if not config.get().delivery_targets():
            raise HTTPException(409, 'Cadastre ao menos um número de WhatsApp nas configurações.')
        return {'id': alerts.send_test()}

    return router
