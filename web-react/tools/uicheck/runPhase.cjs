"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/utils/runPhase.ts
var runPhase_exports = {};
__export(runPhase_exports, {
  phaseOf: () => phaseOf
});
module.exports = __toCommonJS(runPhase_exports);
var PHASES = {
  thinking: "Agent \u6B63\u5728\u601D\u8003...",
  executing: "Agent \u6B63\u5728\u6267\u884C\u5DE5\u5177...",
  reviewing: "Agent \u6B63\u5728\u590D\u6838...",
  routing: "Agent \u6B63\u5728\u5224\u65AD\u662F\u5426\u9700\u8981\u91CD\u8DD1...",
  idle: ""
};
function phaseOf(lastDone) {
  switch (lastDone) {
    case null:
      return { key: "thinking", label: PHASES.thinking };
    case "planner":
      return { key: "executing", label: PHASES.executing };
    case "executor":
      return { key: "reviewing", label: PHASES.reviewing };
    case "reviewer":
      return { key: "routing", label: PHASES.routing };
    default:
      return { key: "thinking", label: PHASES.thinking };
  }
}
