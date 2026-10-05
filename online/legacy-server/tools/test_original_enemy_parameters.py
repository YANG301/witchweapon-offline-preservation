"""原始敌人参数生成器的资料/协议回归检查，不运行客户端或服务端。"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from original_enemy_parameters import (
    AUDIT, EnemyParameterBuilder, ParameterError, _motion_templates,
    parse_stat_id, validate_basket,
)


class OriginalEnemyParametersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = EnemyParameterBuilder()

    def build(self, ids):
        raw, evidence = self.builder.build_basket(ids)
        return self.builder.cls.FromString(raw), evidence

    def test_original_level_one_stats_and_rank(self):
        basket, evidence = self.build(["331010110001-1-1"])
        mob = basket.MobInfos[0]
        # 原CSV直接可核的1级基础数据，避免沿用旧生成器的620HP曲线。
        self.assertEqual((mob.ID, mob.CurType, mob.Level), (331010110001, 1, 1))
        self.assertEqual((mob.Hp, mob.PhysicalAttack, mob.MagicalAttack,
                          mob.PhysicalDefense, mob.MagicalDefense), (1492, 0, 154, 1000, 500))
        self.assertEqual(mob.MobTypeInfoNormal, 3510101100011)
        self.assertEqual((mob.MobTypeInfoElite, mob.MobTypeInfoBoss), (0, 0))
        self.assertFalse(evidence["fullOriginalCombatParameters"])
        self.assertTrue(evidence["gaps"])

    def test_magic_only_enemy_has_nonphysical_compatibility_attack(self):
        basket, evidence = self.build(["331010110001-1-1"])
        tree = basket.BehaviorTreeArgumentInfos[0]
        skill = next(s for s in basket.SpellInfos if s.ID == tree.Argument0)
        self.assertEqual(skill.SpellTempletId, "Mob_NormalAttack_Melee_Magical")
        self.assertTrue(any(o.get("kind") == "local-compatible-magical-normal-attack"
                            for o in evidence["objects"]))

    def test_old_projectile_without_current_motion_id_is_replaced(self):
        basket, evidence = self.build(["331010341601-3-50"])
        self.assertFalse(basket.AgentInfos)
        self.assertTrue(any(g.get("originalID") == 2020141601 and
                            "AgentInfos/36241601缺客户端MotionId" in g.get("reason", "")
                            for g in evidence["gaps"]))
        tree = basket.BehaviorTreeArgumentInfos[0]
        skill = next(s for s in basket.SpellInfos if s.ID == tree.Argument0)
        self.assertEqual(skill.SpellTempletId, "Mob_NormalAttack_Melee_Magical")
        validate_basket(basket)
        self.assertEqual(basket.MobInfos[0].CurType, 3)

    def test_stage_two_four_has_no_unverified_projectile(self):
        # 实机曾在这些原敌人刷出后进入SaveEmit/CreateMotion空对象链。
        ids = ["331010110501-2-8", "331010341601-2-8", "331010342201-1-8",
               "331010343801-1-8", "331010343901-2-8"]
        basket, evidence = self.build(ids)
        self.assertFalse(basket.AgentInfos)
        self.assertFalse(any(s.ID == 2020141601 for s in basket.SpellInfos))
        self.assertEqual({(m.ID, m.CurType, m.Level) for m in basket.MobInfos},
                         {parse_stat_id(value) for value in ids})
        self.assertTrue(any("缺客户端MotionId" in g.get("reason", "")
                            and g.get("replacementID") for g in evidence["gaps"]))
        self.assertTrue(any(p["path"].endswith("motion.xml") for p in evidence["inputs"]))
        validate_basket(basket)

    def test_agent_requires_existing_emit_and_bullet_template(self):
        basket = self.builder.cls()
        agent = basket.AgentInfos.add()
        agent.ID = 36241601
        for motion in ("", "9100141601", "DEFAULT-prefab"):
            agent.MotionId = motion
            with self.subTest(motion=motion), self.assertRaisesRegex(ParameterError, "MotionId|emit/bullet"):
                validate_basket(basket, motion_templates=self.builder.motion_templates)
        # 只验证确有模板的引用；这里不把DEFAULT当作旧投射物的真实映射。
        agent.MotionId = "DEFAULT"
        validate_basket(basket, motion_templates=self.builder.motion_templates)
        with self.assertRaisesRegex(ParameterError, "emit/bullet"):
            validate_basket(basket, motion_templates=frozenset())

    def test_emit_without_bullet_is_not_an_executable_template(self):
        document = ET.ElementTree(ET.fromstring(
            '<config><emit id="WITHOUT_BULLET"/><emit id="COMPLETE"><bullet/></emit></config>'))
        with patch("original_enemy_parameters.ET.parse", return_value=document):
            templates = _motion_templates("内存XML测试，无磁盘临时文件")
        basket = self.builder.cls()
        agent = basket.AgentInfos.add()
        agent.ID, agent.MotionId = 36241601, "WITHOUT_BULLET"
        with self.assertRaisesRegex(ParameterError, "emit/bullet"):
            validate_basket(basket, motion_templates=templates)
        agent.MotionId = "COMPLETE"
        validate_basket(basket, motion_templates=templates)

    def test_duplicate_inputs_and_levels_do_not_overwrite(self):
        ids = ["331010240201-1-1", "331010240201-1-2", "331010240201-1-1"]
        raw, first = self.builder.build_basket(ids)
        other, _ = self.builder.build_basket(reversed(ids))
        self.assertEqual(raw, other)
        basket = self.builder.cls.FromString(raw)
        self.assertEqual(len(basket.MobInfos), 2)
        self.assertEqual(len(basket.MobTypeInfos), 1)
        self.assertNotEqual(basket.MobInfos[0].Hp, basket.MobInfos[1].Hp)
        first["inputs"][0]["sha256"] = "caller-change"
        _, again = self.builder.build_basket(ids)
        self.assertNotEqual(again["inputs"][0]["sha256"], "caller-change")

    def test_missing_and_invalid_data_fail_explicitly(self):
        for value in ("1-0-1", "331010110001-1", "331010110001-1--1"):
            with self.assertRaises(ParameterError):
                parse_stat_id(value)
        for ids in ([], ["1-1-1"], ["331010110001-1-106"]):
            with self.assertRaises(ParameterError):
                self.builder.build_basket(ids)

    def test_dangling_skill_is_rejected(self):
        basket, _ = self.build(["331010110001-1-1"])
        basket.MobTypeInfos[0].MobSpell1 = 123456789
        with self.assertRaisesRegex(ParameterError, "悬空引用"):
            validate_basket(basket)

    def test_all_247_complete_stage_references_build(self):
        data = json.loads((AUDIT / "编辑器战斗数据补充核查.json").read_text(encoding="utf-8"))
        stages = [s for s in data["currentStageReferences"] if s.get("references") and not s.get("issues")]
        self.assertEqual(len(stages), 247)
        for stage in stages:
            with self.subTest(stageID=stage["stageID"]):
                ids = [r["statID"] for r in stage["references"]]
                basket, evidence = self.build(ids)
                self.assertEqual({(m.ID, m.CurType, m.Level) for m in basket.MobInfos},
                                 {parse_stat_id(value) for value in ids})
                validate_basket(basket)
                json.dumps(evidence, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
