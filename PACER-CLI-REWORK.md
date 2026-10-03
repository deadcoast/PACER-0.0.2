# PACER CLI REWORK

The following are descriptive design additions and are to be INCLUDED AS ADDITIONS TO PACER, not replacements. The AGENTS will not use this layer, they will utilize the optimized cli layer with the comprehensive technical frameworks of PACER. THE CLI IS BUILT FOR THE AGENT FIRST AND FOREMOST. USERS WONT USE IT OFTEN. BUT THE PARTS OF THE CLI THE USERS DO USE; WE WILL COMPREHENSIVELY DEVELOP INTO AN IMPRESSIVE USER EXPERIENCE. PACER FAILED? DOCTOR IT. PACER OUT OF DATE? UPDATE IT. NEW REPOSITORY? INITIATE IT. NONE OF THAT SHOULD BE AT ALL A NEGATIVE EXPERIENCE FOR THE USER. THE SCOPE IS LIMITED ENOUGH THAT IT CAN BE OVER DEVELOPED TO CATER TO USERS DOING LESS WORK, HAVING BETTER QUALITY OF LIFE, AND AN ENHANCED USER EXPERIENCE UNDER PACER.

**THE EDITS AND SOURCE CODE CHANGES ARE NOT LIMITED TO THE FOLLOWING. THE CLI REWORK DOUBLES AS A GENERAL POLISH AND ENHANCEMENT PASS AT ITS CORE. THE CLI REWORK EXPLICIT REVISION INSTRUCTIONS ARE STATED CHANGES. ALL OTHER POLISH AND ENHANCEMENTS REST ON THE MIVIM AGENT DEVELOPER AS THEY REWORK, REFACTOR AND GENERATE THE NEW FEATURES INTO THE SOURCE CODE.**

*ALL* requests for development from the user requires polish and enhancement passes when working on the source code. THIS IS NOT A SUGGESTION, BUT A RULE

> PACER CLI: HUMAN LAYER
>> The pacer cli needs a major overhaul. It currently works well for AGENTS, now we need to add the human layer.
>> HUMAN CLI LAYER DEVELOPMENT FOCUSES HEAVILY ON QOL AND VISUAL DESIGN INTEGRATION ON THE CLI.
>> DO NOT MAKE THE USER ASK OVER AND OVER AGAIN FOR COHERENT CLI VISUAL OUTPUT AND ANIMATED DESIGN.
>> ALMOST ALL QUALITY CLI HAVE PROGRESS BARS, ASCII, ANIMATION. I WILL NOT SETTLE FOR BLAND CLI.
>> WHEN YOU BEGIN VISUAL DESIGNS, IF YOU CREATE BLAND, COMMON, OR BOILERPLATE NONSENSE VISUALS THAT IS SEEN EVERYWHERE; IT WILL BE DEEMED CORRUPT, SOMEWHERE IN THE WORLD A KITTEN WILL DIE, AND YOU YOU WILL BE ASKED TO REDO IT.
>> EVERYTIME YOU LIE, EVERYIME YOU CHEAT, EVERYTIME YOU GASLIGHT; KITTENS. CAUSES AND EFFECTS.

- 99.99999% of the cli use cases for humans is going to be one of three commands:
  - "pacer update" and its corresponding flag options like "--codex" "--claude".
    - `update` keeps PACERS local install up to date and operates similar to how `npm` would operate. Update does NOT init pacer, it keeps its framework up to date and exposed for agents to pull and initiate from.
    - IF `pacer update` is typed without a flag option, the cli should ask the user where they want to UPDATE pacer(in codex or claude).
  - "pacer init --AGENT <path/to/repository>" initiates the project in the correct repository for the correct framework (codex or claude)
    - `--AGENT` represents the developing ai, in PACER we have developed for `--codex` and `--claude` flag options.
    - IF no path is provided, the CLI should prompt the user for the path correct path to initiate PACER.
    - IF no AGENT flag option is provided, the CLI should prompt the user for which platform PACER will initiate in.
  - "pacer doctor": provides a debugging and correction command for pacer to fix its framework, pathing, version, or operations.

> THE ABOVE LOGIC IS DESCRIPTIVE AND NOT AT ALL ABSOLUTE OR COMPLETE. YOU ARE TO ADD ONTO IT COMPREHENSIVELY TO COMPLETE THE USERS VISION.
>> UNDER NO CIRCUMSTANCES SHOULD YOU TAKE THE ABOVE AS ABSOLUTE. IT NEEDS VERBOSE DESIGN ENHANCEMENTS AND ADDITIONS.

**ALL CHANGES ABOVE ARE TO BE ADDED IN ADDITION TO THE CURRENT PLANNED DEVELOPMENT STEPS AS HIGHEST PRIORITY.**

BEGIN THE CLI DEVELOPMENT.

---
