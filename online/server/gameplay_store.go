package main

import (
	"errors"
	"math"
	"time"
)

var errMissingRole = errors.New("role required")
var errActiveBattle = errors.New("active battle already exists")
var errBattleNotFound = errors.New("battle not found")
var errSettlementConflict = errors.New("battle already settled with different result")

func (s *store) gameplay(id string) (Role, GameplayState, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.state.Users[id]
	if !ok {
		return Role{}, GameplayState{}, errors.New("missing account")
	}
	if a.Role == nil {
		return Role{}, GameplayState{}, errMissingRole
	}
	return *a.Role, gameplayOf(a), nil
}

func (s *store) startBattle(id, stageID, requestID, battleID string, now time.Time) (Role, GameplayState, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.state.Users[id]
	if !ok {
		return Role{}, GameplayState{}, errors.New("missing account")
	}
	if a.Role == nil {
		return Role{}, GameplayState{}, errMissingRole
	}
	g := gameplayOf(a)
	if g.Battle != nil && g.Battle.RequestID == requestID {
		if g.Battle.StageID != stageID {
			return Role{}, GameplayState{}, errSettlementConflict
		}
		return *a.Role, g, nil
	}
	if g.Battle != nil && g.Battle.Status == "active" {
		return Role{}, GameplayState{}, errActiveBattle
	}
	if g.Battle != nil && g.Battle.ID == battleID {
		return Role{}, GameplayState{}, errors.New("random battle id collision")
	}
	round := 1
	if stageID == mainStageID {
		g.Main.Attempts++
	} else {
		if g.Maze.Round > 12 {
			g.Maze.Round = 1
			g.Maze.Runs++
			g.Maze.HP = 1
		}
		g.Maze.Attempts++
		round = g.Maze.Round
	}
	g.Battle = &BattleState{ID: battleID, StageID: stageID, RequestID: requestID, Round: round, Status: "active", StartedAt: now.UTC()}
	updated := *a
	updated.Gameplay = &g
	next := s.copyState()
	next.Users[id] = &updated
	if err := s.persist(next); err != nil {
		return Role{}, GameplayState{}, err
	}
	s.state = next
	return *a.Role, g, nil
}

func (s *store) finishBattle(id, battleID string, win bool, stars int, hp *float64, now time.Time) (Role, GameplayState, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, ok := s.state.Users[id]
	if !ok {
		return Role{}, GameplayState{}, errors.New("missing account")
	}
	if a.Role == nil {
		return Role{}, GameplayState{}, errMissingRole
	}
	g := gameplayOf(a)
	if g.Battle == nil || g.Battle.ID != battleID {
		return Role{}, GameplayState{}, errBattleNotFound
	}
	if g.Battle.Status == "settled" {
		if g.Battle.Win != win || g.Battle.Stars != stars || (hp != nil && math.Abs(g.Battle.HPAfter-*hp) > 0.000001) {
			return Role{}, GameplayState{}, errSettlementConflict
		}
		return *a.Role, g, nil
	}
	if !win && stars != 0 {
		return Role{}, GameplayState{}, errors.New("lost battle cannot have stars")
	}
	if g.Battle.StageID == mainStageID && hp != nil {
		return Role{}, GameplayState{}, errors.New("main stage does not use HP carry")
	}
	if hp != nil && (math.IsNaN(*hp) || math.IsInf(*hp, 0) || *hp < 0 || *hp > 1) {
		return Role{}, GameplayState{}, errors.New("invalid HP")
	}
	role := *a.Role
	g.Battle.Status = "settled"
	g.Battle.SettledAt = now.UTC()
	g.Battle.Win = win
	g.Battle.Stars = stars
	if win {
		g.Gold += battleGold
		g.Battle.GoldAward = battleGold
		g.Battle.ExperienceAward = battleExperience
		advanceRole(&role, battleExperience)
		if g.Battle.StageID == mainStageID {
			g.Main.Wins++
			if stars > g.Main.BestStars {
				g.Main.BestStars = stars
			}
		} else {
			g.Maze.Wins++
			if stars > g.Maze.BestStars {
				g.Maze.BestStars = stars
			}
			g.Maze.Round = g.Battle.Round + 1
			if hp != nil {
				g.Maze.HP = math.Max(0.01, *hp)
			}
			if g.Battle.Round%3 == 0 {
				g.Gold += mazeCheckpointGold
				g.Battle.GoldAward += mazeCheckpointGold
				g.Maze.SupplyBoxes++
				g.Maze.HP = math.Min(1, g.Maze.HP+0.30)
			}
			g.Battle.HPAfter = g.Maze.HP
		}
	} else if g.Battle.StageID == mazeStageID {
		g.Battle.HPAfter = g.Maze.HP
	}
	updated := *a
	updated.Role = &role
	updated.Gameplay = &g
	next := s.copyState()
	next.Users[id] = &updated
	if err := s.persist(next); err != nil {
		return Role{}, GameplayState{}, err
	}
	s.state = next
	return role, g, nil
}
