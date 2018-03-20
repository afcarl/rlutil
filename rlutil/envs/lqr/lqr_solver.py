import numpy as np
import scipy as sp

def lqr_inf(

        ):
    """
    Infinite Horizon LQR
    """
    raise NotImplementedError()


def lqr_fin(T, Fm, fv, Cm, cv):
    """
    Discrete time, finite horizon LQR solver

    The dynamical system is described as 
    x_{t+1} = Fm * x_t + fv

    The cost function is
    0.5 * [x, u]^T * Cm * [x, u] + cv * [x, u]

    Args:
        T (int): Time horizon
        Fm (np.ndarray): A dX x (dX+dU) dynamics matrix
        fv (np.ndarray): A dX x 1 dynamics bias
        Cm (np.ndarray): A (dX+dU) x (dX+dU) quadratic cost term
        cv (np.ndarray): A (dX+dU) x 1 linear cost term

    Returns:
        K: Policy parameters (linear term)
        k: Policy parameters (bias term)
        Vxx: Value function (quadratic term)
        Vx: Value function (linear term)
        Qtt: Q-value function (quadratic term)
        Qt: Q-value function (linear term)
    """
    dX, dXdU = Fm.shape
    dU = dXdU - dX
    idx_x = slice(0, dX)
    idx_u = slice(dX, dX+dU)

    Vxx = np.zeros((T, dX, dX))
    Vx = np.zeros((T, dX))
    Qtt = np.zeros((T, dX+dU, dX+dU))
    Qt = np.zeros((T, dX+dU))
    K = np.zeros((T, dU, dX))
    k = np.zeros((T, dU))

    # Compute state-action-state function at each time step.
    for t in range(T - 1, -1, -1):
        # Add in the cost.
        Qtt[t] = Cm[:,:] # (X+U) x (X+U)
        Qt[t] = cv[:] # (X+U) x 1

        # Add in the value function from the next time step.
        if t < T - 1:
            #Qtt[t] += Fm[t, :, :].T.dot(Vxx[t+1, :, :]).dot(Fm[t, :, :])
            #Qt[t] += Fm[t, :, :].T.dot(Vx[t+1, :] + Vxx[t+1, :, :].dot(fv[t, :]))
            Qtt[t] += Fm.T.dot(Vxx[t+1, :, :]).dot(Fm)
            Qt[t] += Fm.T.dot(Vx[t+1, :] + Vxx[t+1, :, :].dot(fv))

        # Symmetrize quadratic component.
        Qtt[t] = 0.5 * (Qtt[t] + Qtt[t].T)

        inv_term = Qtt[t, idx_u, idx_u]
        k_term = Qt[t, idx_u]
        K_term = Qtt[t, idx_u, idx_x]

        # Compute Cholesky decomposition of Q function action
        # component.
        U = sp.linalg.cholesky(inv_term)
        L = U.T

        # Compute mean terms
        k[t, :] = -sp.linalg.solve_triangular(
            U, sp.linalg.solve_triangular(L, k_term, lower=True)
        )
        K[t, :, :] = -sp.linalg.solve_triangular(
            U, sp.linalg.solve_triangular(L, K_term, lower=True)
        )

        Vxx[t, :, :] = Qtt[t, idx_x, idx_x] + \
                Qtt[t, idx_x, idx_u].dot(K[t, :, :])
        Vx[t, :] = Qt[t, idx_x] + \
                Qtt[t, idx_x, idx_u].dot(k[t, :])
        Vxx[t, :, :] = 0.5 * (Vxx[t, :, :] + Vxx[t, :, :].T)
    return K, k, Vxx, Vx, Qtt, Qt


def solve_lqr_env(lqrenv, T):
    #Fm, fv, Cm, cv
    dX, dU = lqrenv.dO, lqrenv.dA
    Fm = lqrenv.dynamics
    fv = np.zeros(dX)

    Cm = np.zeros((dX+dU, dX+dU))
    Cm[0:dX, 0:dX] = -lqrenv.rew_Q
    Cm[dX:dX+dU, dX:dX+dU] = -lqrenv.rew_R
    Cm = Cm*2

    cv = np.zeros((dX+dU))
    cv[0:dX] = -lqrenv.rew_q
    return lqr_fin(T, Fm, fv, Cm, cv)


