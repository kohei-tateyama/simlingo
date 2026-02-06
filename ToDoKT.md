# 🛠️ Engineering Work Log

**Current Focus:** Deploying a parking VLA into a car and testing out my engineering skills
[x] : Done
[!] : Blocked
---

## 📅 Priorities (Today)
- [ ] Run the training locally/azure with 6 images
- [ ] Run the training locally with collected carla data (1 image)
- [ ] Run the vlm auto annotation pipeline
- [ ] Discuss further about parking data with kutsuwa san
- [ ] Fully understand the simlingo training pipeline. Architecture/which parameters are being trained/tokenization methods/action tokens/trajectory decoding
- [ ] Talk to Sven san about write permission issue


---
THIS WEEK
- [!] Run the training of simlingo on azureml
- [!] Run the simlingo inference on azureml
- [ ] Fix the core issue about the network with Jason san
- [ ] If there is a bug with the inference code, fix 
    -> Trajectory decoding

- [ ] Read the final part of the alpamayo paper
- [ ] Summarize Alpamayo and push to github
- [ ] Read the FLEX paper
---

QUEUE
- [ ] Test out the Alpasim
- [ ] Watch lectures on ECU and embeddings


### Knowledge to gain
- [ ] Tokenization
    - [ ] Action tokenization
    - [ ] Flow matching
    - [ ] Image tokenization (vision encoders)
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


---
## History

### WEEK1 0126-0130
- [x] Check the bin->csv processing logic
- [x] Answer Kutsuwa san
- [x] Verify if it works with flipping
- [x] Fix the code to Flip. use the config is_flipped bool
- [x] Turn it into exe and send it to yamada san and kutsuwa san
- [x] My time. ask yamada san or kutsuwa san
- [x] Clean up simlingo repository
- [x] Make worktree for michele
- [x] Make a repository for paper summarization/implementation
- [x] Update daily log for yesterday
- [x] Infer Alpamayo
- [x] Push the alpamayo inference code to github


### WEEK2 0202-0206
- [x] Debug the network error on azure
- [x] Make a visual for Alpamayo inference
- [x] Create a docker image for simlingo
- [x] Push the docker image to azureml
- [x] Discuss about the data collection for parking
- [x] Finish the OMG task
- [x] Talk to Shono san about the OMG task
- [x] Reference dataset for training on azureml
- [x] Check all the OMG messages
- [x] Watch CES2026 videos
- [x] Make a summary slide for what we did
- [x] Make a proposal slide for the parking VLA
- [x] Run the inference on real world image sequences



### WEEK3 0209-0213


### WEEK4 0216-0220


### WEEK5 0223-0227