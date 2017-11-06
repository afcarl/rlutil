import numpy as np
import sys
import gym
import gym.spaces
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from rllab.misc import logger

from rlutil.envs import log_utils
from rlutil.envs.gridcraft.grid_spec import *
from rlutil.envs.gridcraft.utils import one_hot_to_flat, flat_to_one_hot

ACT_NOOP = 0
ACT_UP = 1
ACT_DOWN = 2
ACT_LEFT = 3
ACT_RIGHT = 4
ACT_DICT = {
    ACT_NOOP: [0,0],
    ACT_UP: [0, -1],
    ACT_LEFT: [-1, 0],
    ACT_RIGHT: [+1, 0],
    ACT_DOWN: [0, +1]
}
ACT_TO_STR = {
    ACT_NOOP: 'NOOP',
    ACT_UP: 'UP',
    ACT_LEFT: 'LEFT',
    ACT_RIGHT: 'RIGHT',
    ACT_DOWN: 'DOWN'
}

class TransitionModel(object):
    def __init__(self, gridspec, eps=0.2):
        self.gs = gridspec
        self.eps = eps

    def get_aprobs(self, s, a):
        # TODO: could probably output a matrix over all states...
        legal_moves = self.__get_legal_moves(s)
        if a in legal_moves:
            p = np.zeros(len(ACT_DICT))
            p[legal_moves] = self.eps / (len(legal_moves)-1)
            p[a] = 1.0-self.eps
        else:
            p = np.array([1.0,0,0,0,0])  # NOOP
        return p

    def __get_legal_moves(self, s):
        xy = np.array(self.gs.idx_to_xy(s))
        moves = [move for move in ACT_DICT if not self.gs.out_of_bounds(xy+ACT_DICT[move])
                                             and self.gs[xy+ACT_DICT[move]] != WALL]

        #print 'xy:', s, xy
        #print [xy+ACT_DICT[move] for move in ACT_DICT]
        #print 'legal:', [ACT_TO_STR[move] for move in moves]

        return moves


class RewardFunction(object):
    def __init__(self, rew_map=None):
        if rew_map is None:
            rew_map = {
                REWARD: 1.0,
                REWARD2: 0.5,
                REWARD3: 0.1,
                REWARD4: -1
            }
        self.rew_map = rew_map

    def __call__(self, gridspec, s, a, ns):
        val = gridspec[gridspec.idx_to_xy(ns)]
        if val in self.rew_map:
            return self.rew_map[val]
        return 0.0


class ObservationModel(object):
    def state_to_obs(self, state, gs):
        raise NotImplementedError()

    def to_state(self, obs, gs, env_info):
        raise NotImplementedError()


class OneHotObsModel(ObservationModel):
    def __init__(self, coordinatewise=False, add_eyes=False):
        self.cwise = coordinatewise
        self.add_eyes = add_eyes

    def state_to_obs(self, state, gs):
        if self.cwise:
            xy = gs.idx_to_xy(state)
            x = flat_to_one_hot(xy[0], gs.width)
            y = flat_to_one_hot(xy[1], gs.height)
            obs = np.r_[x, y]
        else:
            obs = flat_to_one_hot(state, len(gs))

        if self.add_eyes:
            # detect neighboring walls
            neighbors = gs.get_neighbors(state)
            wall_eyes = np.array([1 if (nb in [WALL, OUT_OF_BOUNDS]) else 0 for nb in neighbors])
            rew_eyes = np.array([1 if (nb in [REWARD]) else 0 for nb in neighbors])
            obs = np.r_[wall_eyes, rew_eyes, obs]
        return obs

    def to_state(self, obs, gs, env_info):
        if self.add_eyes: #remove eyes
            obs = obs[:, 8:]
        if self.cwise:
            x = obs[:, :gs.width]
            y = obs[:, gs.width:]
            x = one_hot_to_flat(x)
            y = one_hot_to_flat(y)
            state = gs.xy_to_idx(np.c_[x,y])
        else:
            state = one_hot_to_flat(obs)
        return state


class LocalObs(object):
    def __init__(self):
        pass

    def state_to_obs(self, state, gs):
        raise NotImplementedError()

    def obs_to_state(self, obs, gs):
        raise ValueError("Cannot convert local obs to state")


class GridEnv(gym.Env):
    def __init__(self, gridspec, tiles=TILES, rew_fn=None, one_hot=False,
                 add_eyes=False, teps=0.0, coordinate_wise=False, frameskip=None,
                 terminate_on_reward=False,
                 zero_reward=False):
        self.gs = gridspec
        assert teps == 0.0, "Must use deterministic transitions"
        self.model = TransitionModel(gridspec, eps=teps)
        self.one_hot = one_hot
        if rew_fn is None:
            rew_fn = RewardFunction()
        self.rew_fn = rew_fn
        self.eyes = add_eyes
        self.coordinatewise = coordinate_wise
        self.frameskip = frameskip
        self.zero_reward = zero_reward
        self.terminate_on_reward = terminate_on_reward
        self.possible_tiles = tiles
        super(GridEnv, self).__init__()

    def step_stateless(self, s, a, verbose=False):
        aprobs = self.model.get_aprobs(s, a)
        samp_a = np.random.choice(range(5), p=aprobs)

        next_s = self.gs.idx_to_xy(s) + ACT_DICT[samp_a]
        next_s_idx = self.gs.xy_to_idx(next_s)
        rew = self.rew_fn(self.gs, s, samp_a, next_s_idx)

        if verbose:
            print('Act: %s. Act Executed: %s' % (ACT_TO_STR[a], ACT_TO_STR[samp_a]))

        return next_s_idx, rew

    def step(self, a, verbose=False):
        if self.frameskip is not None:
            ns = self.__state
            r = 0
            states_visited = []
            for _ in range(self.frameskip):
                ns, r = self.step_stateless(ns, a, verbose=verbose)
                states_visited.append(ns)
            traj_infos = {'frameskip_states': np.array(states_visited),
                          'frameskip_observations': np.array([self.state_to_obs(state) for state in states_visited]),
                          'frameskip_actions': np.array([a]*self.frameskip)}
        else:
            ns, r = self.step_stateless(self.__state, a, verbose=verbose)
            traj_infos = {}
        self.__state = ns
        obs = self.state_to_obs(ns)

        if self.zero_reward:
            traj_infos['task_reward'] = r
            r = 0.0

        done = False
        if self.terminate_on_reward:
            if r > 0:
                done = True

        return obs, r, done, traj_infos

    def reset(self):
        start_idxs = np.array(np.where(self.gs.spec == START)).T
        start_idx = start_idxs[np.random.randint(0, start_idxs.shape[0])]
        start_idx = self.gs.xy_to_idx(start_idx)
        self.__state =start_idx
        return self.state_to_obs(start_idx)

    def state_to_obs(self, state):
        if self.one_hot:
            if self.coordinatewise:
                xy = self.gs.idx_to_xy(state)
                x = flat_to_one_hot(xy[0], self.gs.width)
                y = flat_to_one_hot(xy[1], self.gs.height)
                obs = np.r_[x, y]
            else:
                obs = flat_to_one_hot(state, len(self.gs))

            if self.eyes:
                # detect neighboring walls
                neighbors = self.gs.get_neighbors(state)
                wall_eyes = np.array([1 if (nb in [WALL, OUT_OF_BOUNDS]) else 0 for nb in neighbors])
                rew_eyes = np.array([1 if (nb in [REWARD]) else 0 for nb in neighbors])
                obs = np.r_[wall_eyes, rew_eyes, obs]
        else:
            obs = state
        return obs

    def obs_to_state(self, obs):

        expanded = False
        if len(obs.shape) == 1:
            obs = np.expand_dims(obs, axis=0)
            expanded = True

        if self.one_hot:
            if self.eyes: #remove eyes
                obs = obs[:, 8:]
            if self.coordinatewise:
                x = obs[:, :self.gs.width]
                y = obs[:, self.gs.width:]
                x = one_hot_to_flat(x)
                y = one_hot_to_flat(y)
                state = self.gs.xy_to_idx(np.c_[x,y])
            else:
                state = one_hot_to_flat(obs)
        else:
            state = obs

        if expanded:
            state = state[0]

        return state

    def get_tile(self, obs):
        idx = self.obs_to_state(obs)
        return self.gs.get_value(idx)

    def render(self, close=False, ostream=sys.stdout):
        if close:
            return

        state = self.__state
        ostream.write('-'*(self.gs.width+2)+'\n')
        for h in range(self.gs.height):
            ostream.write('|')
            for w in range(self.gs.width):
                if self.gs.xy_to_idx((w,h)) == state:
                    ostream.write('*')
                else:
                    val = self.gs[w, h]
                    ostream.write(RENDER_DICT[val])
            ostream.write('|\n')
        ostream.write('-' * (self.gs.width + 2)+'\n')

    @property
    def action_space(self):
        return gym.spaces.Discrete(5)

    @property
    def observation_space(self):
        dO = len(self.gs)
        if self.one_hot:
            if self.coordinatewise:
                dO = self.gs.width + self.gs.height
            if self.eyes:
                dO += 8
            return gym.spaces.Box(0,1,shape=dO)
        else:
            return gym.spaces.Discrete(dO)

    def log_diagnostics(self, paths):
        Ntraj = len(paths)
        acts = np.array([traj['actions'] for traj in paths])
        obs = np.array([traj['observations'] for traj in paths])

        state_count = np.sum(obs, axis=1)
        states_visited = np.sum(state_count>0, axis=-1)
        #log states visited
        logger.record_tabular('AvgStatesVisited', np.mean(states_visited))


        if self.zero_reward:
             task_reward = np.array([traj['env_infos']['task_reward'] for traj in paths])
             logger.record_tabular('ZeroedTaskReward', np.mean(np.sum(task_reward, axis=1)))


    def plot_trajs(self, paths, dirname=None, itr=0):
        plt.figure()
        # draw walls
        ax = plt.gca()
        wall_positions = self.gs.find(WALL)
        for i in range(wall_positions.shape[0]):
            wall_xy = wall_positions[i,:]
            wall_xy[1] = self.gs.height-wall_xy[1]-1
            ax.add_patch(Rectangle(wall_xy-0.5, 1, 1))
        #plt.scatter(wall_positions[:,0], wall_positions[:,1], color='k')

        val_to_color = {
            REWARD: (0,0.2,0.0),
            REWARD2: (0.0, 0.5, 0.0),
            REWARD3: (0.0, 1.0, 0.0),
            REWARD4: (1.0, 0.0, 1.0),
            START: 'b',
        }
        for key in val_to_color:
            rew_positions = self.gs.find(key)
            plt.scatter(rew_positions[:,0], self.gs.height-rew_positions[:,1]-1, color=val_to_color[key])

        for path in paths:
            if self.frameskip:
                obses = path['env_infos']['frameskip_states'].flatten()
            else:
                obses = self.obs_to_state(path['observations'])
            xys = self.gs.idx_to_xy(obses)
            # plot x, y positions
            plt.plot(xys[:,0], self.gs.height-xys[:,1]-1)

        ax.set_xticks(np.arange(-1, self.gs.width+1, 1))
        ax.set_yticks(np.arange(-1, self.gs.height+1, 1))
        plt.grid()

        if dirname is not None:
            log_utils.record_fig('trajs_itr%d'%itr, subdir=dirname, rllabdir=True)
        else:
            plt.show()


    def plot_costs(self, paths, cost_fn, dirname=None, itr=0, policy=None,
                   use_traj_paths=False):
        #costs = cost_fn.eval(paths)
        if self.gs.width*self.gs.height > 600:
            use_text = False
        else:
            use_text = True


        if not use_traj_paths:
            # iterate through states, and each action - makes sense for non-rnn costs
            import itertools
            obses = []
            acts = []
            for (x, y, a) in itertools.product(range(self.gs.width), range(self.gs.height), range(5)):
                obs = self.state_to_obs(self.gs.xy_to_idx((x, y)))
                act = flat_to_one_hot(a, ndim=5)
                obses.append(obs)
                acts.append(act)
            path = {'observations': np.array(obses), 'actions': np.array(acts)}
            if policy is not None:
                if hasattr(policy, 'set_env_infos'):
                    policy.set_env_infos(path.get('env_infos', {}))
                actions, agent_infos = policy.get_actions(path['observations'])
                path['agent_infos'] = agent_infos
            paths = [path]

        plots = cost_fn.debug_eval(paths, policy=policy)
        for plot in plots:
            plots[plot] = plots[plot].squeeze()

        for plot in plots:
            data = plots[plot]

            plotter = TabularQValuePlotter(self.gs.width, self.gs.height, text_values=use_text)
            for i, (x, y, a) in enumerate(itertools.product(range(self.gs.width), range(self.gs.height), range(5))):
                plotter.set_value(x, self.gs.height-y-1, a, data[i])
            plotter.make_plot()
            if dirname is not None:
                log_utils.record_fig('%s_itr%d'%(plot, itr), subdir=dirname, rllabdir=True)
            else:
                plt.show()

