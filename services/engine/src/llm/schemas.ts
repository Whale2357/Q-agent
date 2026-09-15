import { z } from "zod";

export const candidateSchema = z.object({
  id: z.string(),
  text: z.string(),
  preg_trigger: z.enum([
    "knowledge_gap",
    "contradiction",
    "anomaly",
    "inconsistency",
    "unexpected_outcome",
    "goal_obstacle",
  ]),
  operator: z.enum([
    "assumption_challenge",
    "reframing",
    "criterion_clarification",
    "counterfactual",
    "constraint_relaxation",
  ]),
  category: z.enum(["blind_spot", "essence", "expansion"]),
  depth_hint: z.string().optional(),
});

export const generateResponseSchema = z.object({
  candidates: z.array(candidateSchema).min(1).max(12),
});

export const scoreItemSchema = z.object({
  id: z.string(),
  info_gain: z.number().min(0).max(1),
  hypothetical_answer_summary: z.string(),
  action_before: z.string().optional(),
  action_after: z.string().optional(),
  rationale: z.string(),
});

export const scoreResponseSchema = z.object({
  scores: z.array(scoreItemSchema).min(1),
});
