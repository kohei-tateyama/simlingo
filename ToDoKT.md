# 🛠️ Engineering Work Log

**Current Focus:** Deploying a VLA into a car and testing out my engineering skills

---

## 📅 Priorities (Today)
- [ ] Debug the network error on azure
- [ ] Run the training of simlingo on azureml
- [ ] Run the simlingo inference on azureml
- [ ] Read the alpamayo paper
- [ ] Summarize Alpamayo and push to github
- [x] Infer Alpamayo
- [x] Push the alpamayo inference code to github
- [ ] Finish the OMG task
- [ ] Talk to Shono san about the OMG task
- [ ] Make a visual for Alpamayo inference
- [ ] Make a summary slide for what we did
- [ ] Make a proposal slide

---

NEXT WEEK
- [ ] Discuss about the data collection for parking

## ⚡ Active Development (WIP)
For the future
- [ ] Test out the Alpasim
- [ ] Ask Nav san about side business (Friday 30/jan)



### Knowledge to gain
- [ ] Tokenization
    - [ ] Action tokenization
    - [ ] Flow matching
- [ ] Gain knowledge on transformers
    - [ ] Self attention
    - [ ] Cross attention
    - [ ] Flash attention 3
    - [ ] Rotary Positional Embeddings (RoPE)
- [ ] Reinforcement Learning
    - [ ] Policy gradient (GRPO)
- [ ] Detection-focused backbones (DETR/DINOv2)
    - learn how to handle different input resolutions and patch embeddings
- [ ] Finetuning techniques
    - Parameter efficient fine tuning PEFT
- [ ] 3D gaussian splatting
- [ ] Basic Control Theory
    - [ ] PID control
    - [ ] Model predivtive control
- [ ] Basic embeddings.
    - [ ] How to put softwares into cars
- [ ] C++
- [ ] FusionNet
    - How to implement fusionnet architectures that use cross-attention to merge RGB data with depths
- [ ] Chain of thought
---

## 🧰 Cheat Sheet / Useful Commands
ctrl+shift+'v' to preview md files

**Docker / K8s**
```bash
# Nuke all docker containers and images
docker system prune -a --volumes

# Get logs from a specific pod
kubectl logs -f -l app=backend --tail=20


```

---
## History

### 0128
- [x] Check the bin->csv processing logic
- [x] Answer Kutsuwa san
- [x] Verify if it works with flipping
- [x] Fix the code to Flip. use the confi is_flipped bool
- [x] Turn it into exe and send it to yamada san and kutsuwa san
- [x] My time. ask yamada san or kutsuwa san
- [x] Clean up simlingo repository
- [x] Make worktree for michele
- [x] Make a repository for paper summarization/implementation
- [x] Update daily log for yesterday