import tests._hermetic as HERM
import json
from tests.test_flow import Base
class T(Base):
    def test_x(self):
        self.interview(); self.ws.estimate("demo",0.2); self.ws.approve_budget("demo")
        print(json.dumps(self.ws._read(self.p,"images.json"),indent=1)[:1800])
        print(json.dumps(self.ws._read(self.p,"shots.json"),indent=1)[:1500])
