# 🛠️ Engineering Work Log

**Current Focus:** [Insert Goal, e.g., API Rate Limiting Logic]
**Status:** 🟢 On Track / 🟡 Blocked / 🔴 Critical

---

## 📅 Priorities (Must Do)
- [ ] Task A: Review PR #42
- [ ] Task B: Fix memory leak in worker process
- [ ] Task C: Update environment variables

---

## ⚡ Active Development (WIP)
*Context for current tasks. Add branch names.*
- [ ] **Feature:** User Authentication
    - [x] Create JWT utility
    - [ ] Middleware implementation
    - [ ] *Note:* Need to decide on token expiration time.

---

## 🧰 Cheat Sheet / Useful Commands
*Commands I always forget and need to copy-paste.*

**Docker / K8s**
```bash
# Nuke all docker containers and images
docker system prune -a --volumes

# Get logs from a specific pod
kubectl logs -f -l app=backend --tail=20