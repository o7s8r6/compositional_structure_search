import numpy as np
nax = np.newaxis
import scipy.linalg
import time

import config
from utils import misc


def integration_matrix(m):
    return (np.arange(m)[:,nax] >= np.arange(m)[nax,:]).astype(float)

def sample_single_chain(t, lambda_D, lambda_N):
    m = t.size
    diagonal = lambda_N.copy()
    diagonal[1:] += lambda_D
    diagonal[:-1] += lambda_D
    off_diag = -lambda_D

    a = np.zeros((2, m))
    a[0, 1:] = off_diag
    a[1,:] = diagonal

    # There appears to be a bug in scipy.linalg.solveh_banded, where
    # it expects a row vector for the b argument, when the documentation
    # seems to want a 1-D vector.
    # http://projects.scipy.org/scipy/attachment/ticket/676/test_solveh_banded.py
    #
    # update 7-17-11: they have since fixed the problem, but also removed the Cholesky return value
    if scipy.version.version in ['0.9.0rc2', '0.9.0', '0.10.0']:
        x = scipy.linalg.solveh_banded(a, t * lambda_N)
        c = scipy.linalg.cholesky_banded(a)
    elif scipy.version.version == '0.8.0':
        c, x = scipy.linalg.solveh_banded(a, t * lambda_N)
    elif scipy.version.version == '0.7.1':
        c, x = scipy.linalg.solveh_banded(a, (t * lambda_N)[nax,:])
    else:
        raise RuntimeError('Unknown SciPy version: %s' % scipy.version.version)
    
    x = x.ravel()

    # generate noise
    lower = np.zeros(c.shape)
    lower[0,:] = c[1,:]
    lower[1,:-1] = c[0,1:]
    u = np.random.normal(size=m)
    n = scipy.linalg.solve_banded((1, 0), lower, u)

    assert np.max(np.abs(x + n)) < 1000.

    return x + n

def single_chain_marginal(t, lambda_D, lambda_N):
    m = t.size
    diagonal = lambda_N.copy()
    diagonal[1:] += lambda_D
    diagonal[:-1] += lambda_D
    off_diag = -lambda_D

    a = np.zeros((2, m))
    a[0, 1:] = off_diag
    a[1,:] = diagonal

    # There appears to be a bug in scipy.linalg.solveh_banded, where
    # it expects a row vector for the b argument, when the documentation
    # seems to want a 1-D vector.
    # http://projects.scipy.org/scipy/attachment/ticket/676/test_solveh_banded.py
    # 
    # update 7-17-11: they have since fixed the problem, but also removed the Cholesky return value
    if scipy.version.version in ['0.9.0rc2', '0.9.0', '0.10.0']:
        x = scipy.linalg.solveh_banded(a, t * lambda_N)
    elif scipy.version.version == '0.8.0':
        c, x = scipy.linalg.solveh_banded(a, t * lambda_N)
    elif scipy.version.version == '0.7.1':
        c, x = scipy.linalg.solveh_banded(a, (t * lambda_N)[nax,:])
    else:
        raise RuntimeError('Unknown SciPy version: %s' % scipy.version.version)
    x = x.ravel()

    Lambda = np.diag(diagonal) + np.diag(off_diag, -1) + np.diag(off_diag, 1)
    Sigma = np.linalg.inv(Lambda)
    return x, np.diag(Sigma)


def chain_gibbs(X, obs, D, row_ids=None, row_variance=False):
    m, n = X.shape
    if row_ids is not None:
        row_ids = np.array(row_ids)
        time_steps = (row_ids[1:] - row_ids[:-1]).astype(float)
    else:
        time_steps = np.ones(m-1)
        
    S = D.cumsum(0)
    N = X - S


    if row_variance:
        # UNDO: is this correct?
        sigma_sq_D_rows, sigma_sq_D_cols = misc.sample_noise(D[1:,:] / np.sqrt(time_steps[:,nax]))
        sigma_sq_N_rows, sigma_sq_N_cols = misc.sample_noise(N, obs=obs)
    else:
        sigma_sq_D_rows, sigma_sq_N_rows = np.ones(m-1), np.ones(m)
        sigma_sq_D_cols = misc.sample_col_noise(D[1:,:] / np.sqrt(time_steps[:,nax]))
        sigma_sq_N_cols = misc.sample_col_noise(N)

    #sigma_sq_N_rows = np.clip(sigma_sq_N_rows, 1e-4, 100.)
    #sigma_sq_N_cols = np.clip(sigma_sq_N_cols, 1e-4, 100.)
    #sigma_sq_D_rows = np.clip(sigma_sq_D_rows, 1e-4, 100.)
    #sigma_sq_D_cols = np.clip(sigma_sq_D_cols, 1e-4, 100.)

    #assert False

    for j in range(n):
        sigma_sq_D = sigma_sq_D_rows * sigma_sq_D_cols[j]
        sigma_sq_N = sigma_sq_N_rows * sigma_sq_N_cols[j]

        # UNDO
        sigma_sq_D = sigma_sq_D.clip(1e-4, 100.)
        sigma_sq_N = sigma_sq_N.clip(1e-4, 100.)
        
        S[:,j] = sample_single_chain(X[:,j], 1. / (time_steps * sigma_sq_D), obs[:,j] / sigma_sq_N)
        N[:,j] = X[:,j] - S[:,j]

    D = np.zeros(X.shape)
    D[0,:] = S[0,:]
    D[1:,:] = S[1:,:] - S[:-1,:]
    return D

NUM_ITER = 200

def sample_variance(values):
    a = 1. + 0.5 * values.size
    b = 1. + 0.5 * np.sum(values ** 2)
    prec = np.random.gamma(a, 1. / b)
    prec = np.clip(prec, 1e-4, 1e4)    # avoid numerical issues
    return 1. / prec

def fit_model_old(data_matrix):
    N, D = data_matrix.m, data_matrix.n
    X = data_matrix.sample_latent_values(np.zeros((N, D)), 1.)
    sigma_sq_D = sigma_sq_N = 1.

    row_ids = data_matrix.row_ids
    time_steps = row_ids[1:] - row_ids[:-1]

    states = np.zeros((N, D))
    resid = np.zeros((N, D))
    diff = np.zeros((N-1, D))

    for it in range(NUM_ITER):
        sigma_sq_N_ = sigma_sq_N * np.ones(N)
        for j in range(D):
            states[:, j] = sample_single_chain(X[:, j], 1. / (time_steps * sigma_sq_D), 1. / sigma_sq_N_)
            resid[:, j] = X[:, j] - states[:, j]
            diff[:, j] = states[1:, j] - states[:-1, j]
        sigma_sq_D = sample_variance(diff)
        sigma_sq_N = sample_variance(resid)

        X = data_matrix.sample_latent_values(states, sigma_sq_N)

        misc.print_dot(it+1, NUM_ITER)

    return states, sigma_sq_D, sigma_sq_N

def fit_model(data_matrix, num_iter=NUM_ITER):
    N_orig, N, D = data_matrix.m_orig, data_matrix.m, data_matrix.n
    X = data_matrix.sample_latent_values(np.zeros((N, D)), 1.)
    sigma_sq_D = sigma_sq_N = 1.
    fixed_variance = data_matrix.fixed_variance()

    row_ids = data_matrix.row_ids
    X_full = np.zeros((N_orig, D))
    X_full[row_ids, :] = X

    states = np.zeros((N_orig, D))
    resid = np.zeros((N, D))
    diff = np.zeros((N_orig-1, D))

    t0 = time.time()
    for it in range(num_iter):
        lam_N = np.zeros(N_orig)
        lam_N[row_ids] = 1. / sigma_sq_N
        for j in range(D):
            states[:, j] = sample_single_chain(X_full[:, j], 1. / sigma_sq_D, lam_N)
        resid = X - states[row_ids, :]
        diff = states[1:, :] - states[:-1, :]

        sigma_sq_D = sample_variance(diff)
        if not fixed_variance:
            sigma_sq_N = sample_variance(resid)

        X = data_matrix.sample_latent_values(states[row_ids, :], sigma_sq_N)
        X_full[row_ids, :] = X

        misc.print_dot(it+1, NUM_ITER)

        if time.time() - t0 > 3600.:   # 1 hour
            break

    return states, sigma_sq_D, sigma_sq_N


def sample_chain(X, obs, row_ids=None):
    m, n = X.shape

    # initalize deltas
    X_noise = X + np.random.normal(0., 0.1, size=X.shape)
    D = np.zeros(X_noise.shape)
    D[0,:] = X_noise[0,:]
    D[1:,:] = X_noise[1:,:] - X_noise[:-1,:]

    niter = 50 # UNDO
    for it in range(niter):
        D = chain_gibbs(X, obs, D, row_ids)

    return D
