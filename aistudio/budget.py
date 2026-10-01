"""E4: budget estimate. Pure function, standard library only (may import aistudio.rates).

Contract (tests in tests/test_budget.py):
  estimate(shots_doc: dict, images_doc: dict, rates: dict, existing_images=(), failure: float = 0.0,
           image_rate: float = 0.036, stop_loss_factor: float = 1.3) -> dict
    shots_doc = {"audio": bool, "final_resolution": "720p", "shots": [{"id","model","seconds","resolution"?,"audio"?}]}
    For each shot: res = shot.get("resolution") or shots_doc.get("final_resolution", "720p");
      audio = shot.get("audio", shots_doc.get("audio", False));
      cost = clip_cost(rates, model, res, seconds, audio) / (1 - failure)   (clip_cost from aistudio.rates)
    stills = image_rate * number of entries in images_doc["images"] whose "id" is NOT in existing_images.
    Returns {"per_shot": [{"id","seconds","cost"}] (cost rounded 6), "clips": sum of shot costs, "stills": float,
             "estimate": round(clips + stills, 2), "stop_loss": round((clips + stills) * stop_loss_factor, 2),
             "footage_seconds": sum of seconds, "failure_rate": failure}.
    failure must be 0 <= failure < 0.9, else ValueError.  A shot whose price is missing in rates raises KeyError.
"""
from aistudio.rates import clip_cost


def estimate(shots_doc, images_doc, rates, existing_images=(), failure=0.0, image_rate=0.036, stop_loss_factor=1.3):
    if not (0 <= failure < 0.9):
        raise ValueError
    
    existing_set = set(existing_images)
    final_resolution = shots_doc.get("final_resolution", "720p")
    global_audio = shots_doc.get("audio", False)
    
    per_shot = []
    clips_total = 0.0
    footage_seconds = 0
    
    for shot in shots_doc.get("shots", []):
        shot_id = shot["id"]
        model = shot["model"]
        seconds = shot["seconds"]
        res = shot.get("resolution", final_resolution)
        audio = shot.get("audio", global_audio)
        
        cost = clip_cost(rates, model, res, seconds, audio) / (1 - failure)
        cost = round(cost, 6)
        
        per_shot.append({"id": shot_id, "seconds": seconds, "cost": cost})
        clips_total += cost
        footage_seconds += seconds
    
    stills_count = sum(1 for img in images_doc.get("images", []) if img.get("id") not in existing_set)
    stills = image_rate * stills_count
    
    total = clips_total + stills
    estimate_val = round(total, 2)
    stop_loss = round(total * stop_loss_factor, 2)
    
    return {
        "per_shot": per_shot,
        "clips": clips_total,
        "stills": stills,
        "estimate": estimate_val,
        "stop_loss": stop_loss,
        "footage_seconds": footage_seconds,
        "failure_rate": failure
    }
