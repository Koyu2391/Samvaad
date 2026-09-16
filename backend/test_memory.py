from core.memory import extract_user_facts
import json

message = "Hi, my name is John and my favorite food is pizza. I am an engineer."
facts = extract_user_facts(message)
print("SUCCESS =>", json.dumps(facts))
