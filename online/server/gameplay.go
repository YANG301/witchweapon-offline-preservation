package main

import (
	_ "embed"
	"encoding/json"
	"errors"
	"math"
	"regexp"
	"strconv"
	"time"
)

// These are the two encounters for which the preservation project has mutable
// battle progress. Other entries in offline_responses.json are fixtures, not
// proof that their server-side rules have been reconstructed.
const mainStageID = "3110001002"
const mazeStageID = "3110001003"

const initialGold = 1000000
const battleGold = 1000
const battleExperience = 5
const mazeCheckpointGold = 10000

var requestIDPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

//go:embed role_levels.json
var roleLevelsJSON []byte

var roleLevelCosts = func() map[string]int {
	var result map[string]int
	if err := json.Unmarshal(roleLevelsJSON, &result); err != nil || len(result) != 100 {
		panic("invalid embedded role level costs")
	}
	return result
}()

type StageProgress struct {
	Attempts  int `json:"attempts"`
	Wins      int `json:"wins"`
	BestStars int `json:"bestStars"`
}

type MazeProgress struct {
	StageProgress
	Round       int     `json:"round"`
	Runs        int     `json:"runs"`
	HP          float64 `json:"hp"`
	SupplyBoxes int     `json:"supplyBoxes"`
}

// BattleState is a single active or last settled encounter. A request ID is
// supplied by the client for retry safety; it is never accepted as authority
// to modify another account or award a second reward.
type BattleState struct {
	ID              string    `json:"id"`
	StageID         string    `json:"stageId"`
	RequestID       string    `json:"requestId"`
	Round           int       `json:"round"`
	Status          string    `json:"status"`
	StartedAt       time.Time `json:"startedAt"`
	SettledAt       time.Time `json:"settledAt,omitempty"`
	Win             bool      `json:"win"`
	Stars           int       `json:"stars"`
	GoldAward       int64     `json:"goldAward"`
	ExperienceAward int       `json:"experienceAward"`
	HPAfter         float64   `json:"hpAfter"`
}

type GameplayState struct {
	Gold   int64         `json:"gold"`
	Main   StageProgress `json:"main"`
	Maze   MazeProgress  `json:"maze"`
	Battle *BattleState  `json:"battle,omitempty"`
}

func initialGameplay() GameplayState {
	return GameplayState{Gold: initialGold, Maze: MazeProgress{Round: 1, HP: 1}}
}

func gameplayOf(a *account) GameplayState {
	if a.Gameplay == nil {
		return initialGameplay()
	}
	g := *a.Gameplay
	if a.Gameplay.Battle != nil {
		battle := *a.Gameplay.Battle
		g.Battle = &battle
	}
	return g
}

func validateStageProgress(p StageProgress) bool {
	return p.Attempts >= 0 && p.Wins >= 0 && p.Wins <= p.Attempts && p.BestStars >= 0 && p.BestStars <= 3
}

func validateGameplay(g *GameplayState) error {
	if g == nil { // An existing v1 account does not have gameplay yet.
		return nil
	}
	if g.Gold < 0 || !validateStageProgress(g.Main) || !validateStageProgress(g.Maze.StageProgress) || g.Maze.Round < 1 || g.Maze.Round > 13 || g.Maze.Runs < 0 || g.Maze.SupplyBoxes < 0 || math.IsNaN(g.Maze.HP) || g.Maze.HP < 0.01 || g.Maze.HP > 1 {
		return errors.New("invalid counters or maze status")
	}
	if b := g.Battle; b != nil {
		if b.ID == "" || !requestIDPattern.MatchString(b.RequestID) || b.StartedAt.IsZero() || b.Round < 1 || b.Round > 12 || (b.StageID != mainStageID && b.StageID != mazeStageID) || (b.StageID == mainStageID && b.Round != 1) || (b.Status != "active" && b.Status != "settled") || b.Stars < 0 || b.Stars > 3 || b.GoldAward < 0 || b.ExperienceAward < 0 || math.IsNaN(b.HPAfter) || b.HPAfter < 0 || b.HPAfter > 1 {
			return errors.New("invalid battle")
		}
		if (b.Status == "active" && !b.SettledAt.IsZero()) || (b.Status == "settled" && b.SettledAt.IsZero()) {
			return errors.New("battle settlement time mismatches status")
		}
	}
	return nil
}

func advanceRole(role *Role, experience int) {
	role.Experience += experience
	for role.Level < 100 {
		cost, ok := roleLevelCosts[strconv.Itoa(role.Level)]
		if !ok || cost <= 0 || role.Experience < cost {
			break
		}
		role.Experience -= cost
		role.Level++
	}
}
