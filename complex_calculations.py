#!/usr/bin/env python3
"""
Complex Calculations Script
A comprehensive Python script demonstrating various complex mathematical calculations
including numerical analysis, statistics, matrix operations, signal processing,
optimization, and more.
"""

import math
import random
import functools
import itertools
from typing import List, Tuple, Dict, Callable, Optional, Union
from collections import defaultdict
import time


# =============================================================================
# SECTION 1: PRIME NUMBER CALCULATIONS
# =============================================================================

def is_prime(n: int) -> bool:
    """Check if a number is prime using trial division."""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(math.sqrt(n)) + 1, 2):
        if n % i == 0:
            return False
    return True


def sieve_of_eratosthenes(limit: int) -> List[int]:
    """Generate all prime numbers up to a given limit using the Sieve of Eratosthenes."""
    if limit < 2:
        return []

    sieve = [True] * (limit + 1)
    sieve[0] = sieve[1] = False

    for i in range(2, int(math.sqrt(limit)) + 1):
        if sieve[i]:
            for j in range(i * i, limit + 1, i):
                sieve[j] = False

    return [i for i, is_p in enumerate(sieve) if is_p]


def prime_factorization(n: int) -> Dict[int, int]:
    """Return the prime factorization of n as a dictionary of prime: exponent pairs."""
    factors = defaultdict(int)
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors[d] += 1
            n //= d
        d += 1
    if n > 1:
        factors[n] += 1
    return dict(factors)


def goldbach_partition(n: int) -> Optional[Tuple[int, int]]:
    """Find two primes that sum to n (Goldbach's conjecture for even numbers)."""
    if n <= 2 or n % 2 != 0:
        return None

    primes = set(sieve_of_eratosthenes(n))
    for p in primes:
        if n - p in primes:
            return (p, n - p)
    return None


def miller_rabin_primality(n: int, k: int = 10) -> bool:
    """Miller-Rabin primality test with k rounds."""
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False

    # Write n-1 as 2^r * d
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2

    def check_witness(a: int) -> bool:
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            return True
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                return True
        return False

    for _ in range(k):
        a = random.randrange(2, n - 1)
        if not check_witness(a):
            return False
    return True


def twin_primes(limit: int) -> List[Tuple[int, int]]:
    """Find all twin prime pairs up to limit."""
    primes = sieve_of_eratosthenes(limit)
    twins = []
    for i in range(len(primes) - 1):
        if primes[i + 1] - primes[i] == 2:
            twins.append((primes[i], primes[i + 1]))
    return twins


def prime_counting_function(n: int) -> int:
    """Count the number of primes less than or equal to n."""
    return len(sieve_of_eratosthenes(n))


# =============================================================================
# SECTION 2: MATRIX OPERATIONS
# =============================================================================

class Matrix:
    """A class for matrix operations without external dependencies."""

    def __init__(self, data: List[List[float]]):
        self.data = data
        self.rows = len(data)
        self.cols = len(data[0]) if data else 0

    def __repr__(self) -> str:
        return f"Matrix({self.data})"

    def __str__(self) -> str:
        return '\n'.join(['\t'.join(map(str, row)) for row in self.data])

    def __add__(self, other: 'Matrix') -> 'Matrix':
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrix dimensions must match for addition")
        result = [[self.data[i][j] + other.data[i][j]
                   for j in range(self.cols)] for i in range(self.rows)]
        return Matrix(result)

    def __sub__(self, other: 'Matrix') -> 'Matrix':
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrix dimensions must match for subtraction")
        result = [[self.data[i][j] - other.data[i][j]
                   for j in range(self.cols)] for i in range(self.rows)]
        return Matrix(result)

    def __mul__(self, other: Union['Matrix', float, int]) -> 'Matrix':
        if isinstance(other, (int, float)):
            result = [[self.data[i][j] * other
                       for j in range(self.cols)] for i in range(self.rows)]
            return Matrix(result)

        if self.cols != other.rows:
            raise ValueError("Matrix dimensions incompatible for multiplication")

        result = [[sum(self.data[i][k] * other.data[k][j]
                       for k in range(self.cols))
                   for j in range(other.cols)] for i in range(self.rows)]
        return Matrix(result)

    def transpose(self) -> 'Matrix':
        """Return the transpose of the matrix."""
        result = [[self.data[j][i] for j in range(self.rows)]
                  for i in range(self.cols)]
        return Matrix(result)

    def determinant(self) -> float:
        """Calculate the determinant using LU decomposition."""
        if self.rows != self.cols:
            raise ValueError("Determinant only defined for square matrices")

        n = self.rows
        matrix = [row[:] for row in self.data]  # Deep copy
        det = 1.0

        for col in range(n):
            # Find pivot
            max_row = col
            for row in range(col + 1, n):
                if abs(matrix[row][col]) > abs(matrix[max_row][col]):
                    max_row = row

            if max_row != col:
                matrix[col], matrix[max_row] = matrix[max_row], matrix[col]
                det *= -1

            if abs(matrix[col][col]) < 1e-10:
                return 0.0

            det *= matrix[col][col]

            for row in range(col + 1, n):
                factor = matrix[row][col] / matrix[col][col]
                for j in range(col, n):
                    matrix[row][j] -= factor * matrix[col][j]

        return det

    def inverse(self) -> 'Matrix':
        """Calculate the inverse using Gauss-Jordan elimination."""
        if self.rows != self.cols:
            raise ValueError("Inverse only defined for square matrices")

        n = self.rows
        augmented = [self.data[i] + [1.0 if i == j else 0.0 for j in range(n)]
                     for i in range(n)]

        for col in range(n):
            max_row = col
            for row in range(col + 1, n):
                if abs(augmented[row][col]) > abs(augmented[max_row][col]):
                    max_row = row

            augmented[col], augmented[max_row] = augmented[max_row], augmented[col]

            if abs(augmented[col][col]) < 1e-10:
                raise ValueError("Matrix is singular and cannot be inverted")

            pivot = augmented[col][col]
            for j in range(2 * n):
                augmented[col][j] /= pivot

            for row in range(n):
                if row != col:
                    factor = augmented[row][col]
                    for j in range(2 * n):
                        augmented[row][j] -= factor * augmented[col][j]

        result = [row[n:] for row in augmented]
        return Matrix(result)

    def trace(self) -> float:
        """Calculate the trace of the matrix."""
        if self.rows != self.cols:
            raise ValueError("Trace only defined for square matrices")
        return sum(self.data[i][i] for i in range(self.rows))

    def frobenius_norm(self) -> float:
        """Calculate the Frobenius norm of the matrix."""
        return math.sqrt(sum(self.data[i][j] ** 2
                             for i in range(self.rows)
                             for j in range(self.cols)))

    def row_echelon_form(self) -> 'Matrix':
        """Convert matrix to row echelon form."""
        result = [row[:] for row in self.data]
        pivot_row = 0

        for col in range(self.cols):
            if pivot_row >= self.rows:
                break

            # Find pivot
            max_row = pivot_row
            for row in range(pivot_row + 1, self.rows):
                if abs(result[row][col]) > abs(result[max_row][col]):
                    max_row = row

            if abs(result[max_row][col]) < 1e-10:
                continue

            result[pivot_row], result[max_row] = result[max_row], result[pivot_row]

            # Eliminate below
            for row in range(pivot_row + 1, self.rows):
                factor = result[row][col] / result[pivot_row][col]
                for j in range(col, self.cols):
                    result[row][j] -= factor * result[pivot_row][j]

            pivot_row += 1

        return Matrix(result)

    def rank(self) -> int:
        """Calculate the rank of the matrix."""
        ref = self.row_echelon_form()
        rank = 0
        for row in ref.data:
            if any(abs(x) > 1e-10 for x in row):
                rank += 1
        return rank

    @staticmethod
    def identity(n: int) -> 'Matrix':
        """Create an n x n identity matrix."""
        return Matrix([[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)])

    @staticmethod
    def zeros(rows: int, cols: int) -> 'Matrix':
        """Create a matrix of zeros."""
        return Matrix([[0.0 for _ in range(cols)] for _ in range(rows)])

    @staticmethod
    def random(rows: int, cols: int, low: float = 0, high: float = 1) -> 'Matrix':
        """Create a matrix with random values."""
        return Matrix([[random.uniform(low, high) for _ in range(cols)]
                       for _ in range(rows)])


def lu_decomposition(matrix: Matrix) -> Tuple[Matrix, Matrix]:
    """Perform LU decomposition of a square matrix."""
    n = matrix.rows
    L = Matrix.identity(n)
    U = Matrix([row[:] for row in matrix.data])

    for col in range(n):
        for row in range(col + 1, n):
            if abs(U.data[col][col]) < 1e-10:
                raise ValueError("Zero pivot encountered")
            factor = U.data[row][col] / U.data[col][col]
            L.data[row][col] = factor
            for j in range(col, n):
                U.data[row][j] -= factor * U.data[col][j]

    return L, U


def cholesky_decomposition(matrix: Matrix) -> Matrix:
    """Perform Cholesky decomposition for positive definite matrices."""
    n = matrix.rows
    L = Matrix.zeros(n, n)

    for i in range(n):
        for j in range(i + 1):
            sum_val = sum(L.data[i][k] * L.data[j][k] for k in range(j))

            if i == j:
                val = matrix.data[i][i] - sum_val
                if val <= 0:
                    raise ValueError("Matrix is not positive definite")
                L.data[i][j] = math.sqrt(val)
            else:
                L.data[i][j] = (matrix.data[i][j] - sum_val) / L.data[j][j]

    return L


def qr_decomposition(matrix: Matrix) -> Tuple[Matrix, Matrix]:
    """Perform QR decomposition using Gram-Schmidt process."""
    m, n = matrix.rows, matrix.cols
    Q = Matrix.zeros(m, n)
    R = Matrix.zeros(n, n)

    for j in range(n):
        v = [matrix.data[i][j] for i in range(m)]

        for i in range(j):
            R.data[i][j] = sum(Q.data[k][i] * matrix.data[k][j] for k in range(m))
            for k in range(m):
                v[k] -= R.data[i][j] * Q.data[k][i]

        R.data[j][j] = math.sqrt(sum(x ** 2 for x in v))

        if abs(R.data[j][j]) > 1e-10:
            for k in range(m):
                Q.data[k][j] = v[k] / R.data[j][j]

    return Q, R


def power_iteration(matrix: Matrix, max_iter: int = 1000, tol: float = 1e-10) -> Tuple[float, List[float]]:
    """Find the dominant eigenvalue and eigenvector using power iteration."""
    n = matrix.rows
    v = [random.random() for _ in range(n)]
    norm = math.sqrt(sum(x ** 2 for x in v))
    v = [x / norm for x in v]

    eigenvalue = 0.0

    for _ in range(max_iter):
        # Matrix-vector multiplication
        Av = [sum(matrix.data[i][j] * v[j] for j in range(n)) for i in range(n)]

        # New eigenvalue estimate (Rayleigh quotient)
        new_eigenvalue = sum(Av[i] * v[i] for i in range(n))

        # Normalize
        norm = math.sqrt(sum(x ** 2 for x in Av))
        v = [x / norm for x in Av]

        if abs(new_eigenvalue - eigenvalue) < tol:
            break

        eigenvalue = new_eigenvalue

    return eigenvalue, v


# =============================================================================
# SECTION 3: NUMERICAL INTEGRATION
# =============================================================================

def trapezoidal_rule(f: Callable[[float], float], a: float, b: float, n: int) -> float:
    """Numerical integration using the trapezoidal rule."""
    h = (b - a) / n
    result = 0.5 * (f(a) + f(b))
    for i in range(1, n):
        result += f(a + i * h)
    return result * h


def simpsons_rule(f: Callable[[float], float], a: float, b: float, n: int) -> float:
    """Numerical integration using Simpson's rule."""
    if n % 2 != 0:
        n += 1

    h = (b - a) / n
    result = f(a) + f(b)

    for i in range(1, n):
        x = a + i * h
        if i % 2 == 0:
            result += 2 * f(x)
        else:
            result += 4 * f(x)

    return result * h / 3


def simpsons_38_rule(f: Callable[[float], float], a: float, b: float, n: int) -> float:
    """Numerical integration using Simpson's 3/8 rule."""
    if n % 3 != 0:
        n = n + (3 - n % 3)

    h = (b - a) / n
    result = f(a) + f(b)

    for i in range(1, n):
        x = a + i * h
        if i % 3 == 0:
            result += 2 * f(x)
        else:
            result += 3 * f(x)

    return result * 3 * h / 8


def romberg_integration(f: Callable[[float], float], a: float, b: float,
                        max_iter: int = 10, tol: float = 1e-10) -> float:
    """Romberg integration method for high accuracy."""
    R = [[0.0] * (max_iter + 1) for _ in range(max_iter + 1)]

    h = b - a
    R[0][0] = 0.5 * h * (f(a) + f(b))

    for i in range(1, max_iter + 1):
        h /= 2

        # Trapezoidal approximation
        sum_val = sum(f(a + (2 * k - 1) * h) for k in range(1, 2 ** (i - 1) + 1))
        R[i][0] = 0.5 * R[i - 1][0] + h * sum_val

        # Richardson extrapolation
        for j in range(1, i + 1):
            R[i][j] = R[i][j - 1] + (R[i][j - 1] - R[i - 1][j - 1]) / (4 ** j - 1)

        if i > 0 and abs(R[i][i] - R[i - 1][i - 1]) < tol:
            return R[i][i]

    return R[max_iter][max_iter]


def gaussian_quadrature(f: Callable[[float], float], a: float, b: float, n: int = 5) -> float:
    """Gaussian quadrature integration with Legendre polynomials."""
    # Gauss-Legendre nodes and weights for n=5
    nodes_weights = {
        2: ([0.5773502692, -0.5773502692], [1.0, 1.0]),
        3: ([0.0, 0.7745966692, -0.7745966692], [0.8888888889, 0.5555555556, 0.5555555556]),
        4: ([0.3399810436, -0.3399810436, 0.8611363116, -0.8611363116],
            [0.6521451549, 0.6521451549, 0.3478548451, 0.3478548451]),
        5: ([0.0, 0.5384693101, -0.5384693101, 0.9061798459, -0.9061798459],
            [0.5688888889, 0.4786286705, 0.4786286705, 0.2369268851, 0.2369268851])
    }

    if n not in nodes_weights:
        n = 5

    nodes, weights = nodes_weights[n]

    # Transform from [-1, 1] to [a, b]
    result = 0.0
    for i in range(len(nodes)):
        x = 0.5 * (b - a) * nodes[i] + 0.5 * (b + a)
        result += weights[i] * f(x)

    return result * 0.5 * (b - a)


def monte_carlo_integration(f: Callable[[float], float], a: float, b: float,
                            n_samples: int = 10000) -> Tuple[float, float]:
    """Monte Carlo integration with error estimate."""
    samples = [f(random.uniform(a, b)) for _ in range(n_samples)]
    mean_val = sum(samples) / n_samples
    variance = sum((x - mean_val) ** 2 for x in samples) / (n_samples - 1)

    integral = (b - a) * mean_val
    error = (b - a) * math.sqrt(variance / n_samples)

    return integral, error


def adaptive_quadrature(f: Callable[[float], float], a: float, b: float,
                        tol: float = 1e-6, max_depth: int = 50) -> float:
    """Adaptive quadrature using recursive subdivision."""
    def simpson(f, a, b):
        c = (a + b) / 2
        h = (b - a) / 6
        return h * (f(a) + 4 * f(c) + f(b))

    def recursive_quad(f, a, b, tol, S, depth):
        c = (a + b) / 2
        left = simpson(f, a, c)
        right = simpson(f, c, b)

        if depth >= max_depth:
            return left + right

        if abs(left + right - S) < 15 * tol:
            return left + right + (left + right - S) / 15

        return (recursive_quad(f, a, c, tol / 2, left, depth + 1) +
                recursive_quad(f, c, b, tol / 2, right, depth + 1))

    S = simpson(f, a, b)
    return recursive_quad(f, a, b, tol, S, 0)


# =============================================================================
# SECTION 4: ROOT FINDING ALGORITHMS
# =============================================================================

def bisection_method(f: Callable[[float], float], a: float, b: float,
                     tol: float = 1e-10, max_iter: int = 100) -> Optional[float]:
    """Find root using bisection method."""
    if f(a) * f(b) > 0:
        return None

    for _ in range(max_iter):
        c = (a + b) / 2
        if abs(f(c)) < tol or (b - a) / 2 < tol:
            return c
        if f(c) * f(a) < 0:
            b = c
        else:
            a = c

    return (a + b) / 2


def newton_raphson(f: Callable[[float], float], df: Callable[[float], float],
                   x0: float, tol: float = 1e-10, max_iter: int = 100) -> Optional[float]:
    """Find root using Newton-Raphson method."""
    x = x0
    for _ in range(max_iter):
        fx = f(x)
        dfx = df(x)

        if abs(dfx) < 1e-15:
            return None

        x_new = x - fx / dfx

        if abs(x_new - x) < tol:
            return x_new

        x = x_new

    return x


def secant_method(f: Callable[[float], float], x0: float, x1: float,
                  tol: float = 1e-10, max_iter: int = 100) -> Optional[float]:
    """Find root using secant method."""
    for _ in range(max_iter):
        f0, f1 = f(x0), f(x1)

        if abs(f1 - f0) < 1e-15:
            return None

        x2 = x1 - f1 * (x1 - x0) / (f1 - f0)

        if abs(x2 - x1) < tol:
            return x2

        x0, x1 = x1, x2

    return x1


def regula_falsi(f: Callable[[float], float], a: float, b: float,
                 tol: float = 1e-10, max_iter: int = 100) -> Optional[float]:
    """Find root using Regula Falsi (False Position) method."""
    if f(a) * f(b) > 0:
        return None

    for _ in range(max_iter):
        c = (a * f(b) - b * f(a)) / (f(b) - f(a))

        if abs(f(c)) < tol:
            return c

        if f(c) * f(a) < 0:
            b = c
        else:
            a = c

    return c


def brent_method(f: Callable[[float], float], a: float, b: float,
                 tol: float = 1e-10, max_iter: int = 100) -> Optional[float]:
    """Brent's method for root finding."""
    fa, fb = f(a), f(b)

    if fa * fb > 0:
        return None

    if abs(fa) < abs(fb):
        a, b = b, a
        fa, fb = fb, fa

    c, fc = a, fa
    d = b - a
    mflag = True

    for _ in range(max_iter):
        if abs(fb) < tol:
            return b

        if fa != fc and fb != fc:
            # Inverse quadratic interpolation
            s = (a * fb * fc / ((fa - fb) * (fa - fc)) +
                 b * fa * fc / ((fb - fa) * (fb - fc)) +
                 c * fa * fb / ((fc - fa) * (fc - fb)))
        else:
            # Secant method
            s = b - fb * (b - a) / (fb - fa)

        # Conditions for accepting s
        cond1 = not ((3 * a + b) / 4 < s < b or b < s < (3 * a + b) / 4)
        cond2 = mflag and abs(s - b) >= abs(b - c) / 2
        cond3 = not mflag and abs(s - b) >= abs(c - d) / 2
        cond4 = mflag and abs(b - c) < tol
        cond5 = not mflag and abs(c - d) < tol

        if cond1 or cond2 or cond3 or cond4 or cond5:
            s = (a + b) / 2
            mflag = True
        else:
            mflag = False

        fs = f(s)
        d, c = c, b
        fc = fb

        if fa * fs < 0:
            b, fb = s, fs
        else:
            a, fa = s, fs

        if abs(fa) < abs(fb):
            a, b = b, a
            fa, fb = fb, fa

    return b


def fixed_point_iteration(g: Callable[[float], float], x0: float,
                          tol: float = 1e-10, max_iter: int = 100) -> Optional[float]:
    """Fixed point iteration for solving x = g(x)."""
    x = x0
    for _ in range(max_iter):
        x_new = g(x)
        if abs(x_new - x) < tol:
            return x_new
        x = x_new
    return x


# =============================================================================
# SECTION 5: STATISTICAL FUNCTIONS
# =============================================================================

def mean(data: List[float]) -> float:
    """Calculate the arithmetic mean."""
    return sum(data) / len(data)


def geometric_mean(data: List[float]) -> float:
    """Calculate the geometric mean."""
    product = functools.reduce(lambda x, y: x * y, data)
    return product ** (1 / len(data))


def harmonic_mean(data: List[float]) -> float:
    """Calculate the harmonic mean."""
    return len(data) / sum(1 / x for x in data)


def median(data: List[float]) -> float:
    """Calculate the median."""
    sorted_data = sorted(data)
    n = len(sorted_data)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_data[mid - 1] + sorted_data[mid]) / 2
    return sorted_data[mid]


def mode(data: List[float]) -> List[float]:
    """Calculate the mode(s)."""
    freq = defaultdict(int)
    for x in data:
        freq[x] += 1
    max_freq = max(freq.values())
    return [x for x, f in freq.items() if f == max_freq]


def variance(data: List[float], sample: bool = True) -> float:
    """Calculate variance (sample or population)."""
    m = mean(data)
    sq_diff = sum((x - m) ** 2 for x in data)
    return sq_diff / (len(data) - 1) if sample else sq_diff / len(data)


def standard_deviation(data: List[float], sample: bool = True) -> float:
    """Calculate standard deviation."""
    return math.sqrt(variance(data, sample))


def covariance(x: List[float], y: List[float], sample: bool = True) -> float:
    """Calculate covariance between two datasets."""
    if len(x) != len(y):
        raise ValueError("Datasets must have equal length")

    mx, my = mean(x), mean(y)
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(len(x)))
    return cov / (len(x) - 1) if sample else cov / len(x)


def correlation(x: List[float], y: List[float]) -> float:
    """Calculate Pearson correlation coefficient."""
    return covariance(x, y) / (standard_deviation(x) * standard_deviation(y))


def spearman_correlation(x: List[float], y: List[float]) -> float:
    """Calculate Spearman rank correlation coefficient."""
    def rank(data):
        sorted_indices = sorted(range(len(data)), key=lambda i: data[i])
        ranks = [0.0] * len(data)
        for rank_val, idx in enumerate(sorted_indices, 1):
            ranks[idx] = float(rank_val)
        return ranks

    rx, ry = rank(x), rank(y)
    return correlation(rx, ry)


def percentile(data: List[float], p: float) -> float:
    """Calculate the p-th percentile."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = math.floor(k)
    c = math.ceil(k)

    if f == c:
        return sorted_data[int(k)]

    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def quartiles(data: List[float]) -> Tuple[float, float, float]:
    """Calculate Q1, Q2 (median), Q3."""
    return percentile(data, 25), percentile(data, 50), percentile(data, 75)


def interquartile_range(data: List[float]) -> float:
    """Calculate the interquartile range."""
    q1, _, q3 = quartiles(data)
    return q3 - q1


def skewness(data: List[float]) -> float:
    """Calculate the skewness of a distribution."""
    n = len(data)
    m = mean(data)
    s = standard_deviation(data)
    return (n / ((n - 1) * (n - 2))) * sum(((x - m) / s) ** 3 for x in data)


def kurtosis(data: List[float]) -> float:
    """Calculate the excess kurtosis of a distribution."""
    n = len(data)
    m = mean(data)
    s = standard_deviation(data)

    k4 = sum(((x - m) / s) ** 4 for x in data) / n
    return k4 - 3


def z_score(x: float, mu: float, sigma: float) -> float:
    """Calculate the z-score."""
    return (x - mu) / sigma


def linear_regression(x: List[float], y: List[float]) -> Tuple[float, float, float]:
    """Simple linear regression returning slope, intercept, and R-squared."""
    n = len(x)
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(x[i] * y[i] for i in range(n))
    sum_x2 = sum(xi ** 2 for xi in x)

    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
    intercept = (sum_y - slope * sum_x) / n

    # R-squared
    ss_tot = sum((yi - mean(y)) ** 2 for yi in y)
    ss_res = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return slope, intercept, r_squared


def polynomial_regression(x: List[float], y: List[float], degree: int) -> List[float]:
    """Polynomial regression using least squares."""
    n = len(x)
    X = [[xi ** j for j in range(degree + 1)] for xi in x]

    # Normal equations: (X^T X) coeffs = X^T y
    XtX = [[sum(X[k][i] * X[k][j] for k in range(n))
            for j in range(degree + 1)] for i in range(degree + 1)]
    Xty = [sum(X[k][i] * y[k] for k in range(n)) for i in range(degree + 1)]

    # Solve using Gaussian elimination
    m = degree + 1
    aug = [XtX[i] + [Xty[i]] for i in range(m)]

    for i in range(m):
        max_row = i
        for k in range(i + 1, m):
            if abs(aug[k][i]) > abs(aug[max_row][i]):
                max_row = k
        aug[i], aug[max_row] = aug[max_row], aug[i]

        for k in range(i + 1, m):
            if aug[i][i] != 0:
                c = aug[k][i] / aug[i][i]
                for j in range(i, m + 1):
                    aug[k][j] -= c * aug[i][j]

    coeffs = [0.0] * m
    for i in range(m - 1, -1, -1):
        coeffs[i] = aug[i][m]
        for j in range(i + 1, m):
            coeffs[i] -= aug[i][j] * coeffs[j]
        if aug[i][i] != 0:
            coeffs[i] /= aug[i][i]

    return coeffs


# =============================================================================
# SECTION 6: SPECIAL FUNCTIONS
# =============================================================================

def factorial(n: int) -> int:
    """Calculate factorial of n."""
    if n < 0:
        raise ValueError("Factorial not defined for negative numbers")
    return 1 if n <= 1 else n * factorial(n - 1)


def double_factorial(n: int) -> int:
    """Calculate double factorial n!!."""
    if n <= 0:
        return 1
    result = 1
    while n > 0:
        result *= n
        n -= 2
    return result


def gamma_function(z: float) -> float:
    """Approximation of the gamma function using Lanczos approximation."""
    if z < 0.5:
        return math.pi / (math.sin(math.pi * z) * gamma_function(1 - z))

    z -= 1
    g = 7
    coefficients = [
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167224028,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.9843695780195716e-6,
        1.5056327351493116e-7
    ]

    x = coefficients[0]
    for i in range(1, g + 2):
        x += coefficients[i] / (z + i)

    t = z + g + 0.5
    return math.sqrt(2 * math.pi) * (t ** (z + 0.5)) * math.exp(-t) * x


def beta_function(a: float, b: float) -> float:
    """Calculate the beta function B(a, b)."""
    return gamma_function(a) * gamma_function(b) / gamma_function(a + b)


def binomial_coefficient(n: int, k: int) -> int:
    """Calculate binomial coefficient C(n, k)."""
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1

    k = min(k, n - k)
    result = 1
    for i in range(k):
        result = result * (n - i) // (i + 1)
    return result


def fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number."""
    if n <= 1:
        return n

    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def fibonacci_sequence(n: int) -> List[int]:
    """Generate first n Fibonacci numbers."""
    if n <= 0:
        return []
    if n == 1:
        return [0]

    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq


def lucas_number(n: int) -> int:
    """Calculate the nth Lucas number."""
    if n == 0:
        return 2
    if n == 1:
        return 1

    a, b = 2, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def catalan_number(n: int) -> int:
    """Calculate the nth Catalan number."""
    return binomial_coefficient(2 * n, n) // (n + 1)


def gcd(a: int, b: int) -> int:
    """Calculate greatest common divisor using Euclidean algorithm."""
    while b:
        a, b = b, a % b
    return abs(a)


def lcm(a: int, b: int) -> int:
    """Calculate least common multiple."""
    return abs(a * b) // gcd(a, b)


def extended_gcd(a: int, b: int) -> Tuple[int, int, int]:
    """Extended Euclidean algorithm returning (gcd, x, y) where ax + by = gcd."""
    if a == 0:
        return b, 0, 1

    gcd_val, x1, y1 = extended_gcd(b % a, a)
    x = y1 - (b // a) * x1
    y = x1

    return gcd_val, x, y


def modular_inverse(a: int, m: int) -> Optional[int]:
    """Calculate modular multiplicative inverse of a mod m."""
    g, x, _ = extended_gcd(a % m, m)
    if g != 1:
        return None
    return (x % m + m) % m


def modular_exponentiation(base: int, exp: int, mod: int) -> int:
    """Fast modular exponentiation using binary method."""
    result = 1
    base = base % mod
    while exp > 0:
        if exp % 2 == 1:
            result = (result * base) % mod
        exp = exp >> 1
        base = (base * base) % mod
    return result


def chinese_remainder_theorem(remainders: List[int], moduli: List[int]) -> int:
    """Solve system of linear congruences using Chinese Remainder Theorem."""
    if len(remainders) != len(moduli):
        raise ValueError("Lists must have equal length")

    M = functools.reduce(lambda a, b: a * b, moduli)
    result = 0

    for i in range(len(remainders)):
        Mi = M // moduli[i]
        yi = modular_inverse(Mi, moduli[i])
        if yi is None:
            raise ValueError("Moduli must be pairwise coprime")
        result += remainders[i] * Mi * yi

    return result % M


def stirling_first(n: int, k: int) -> int:
    """Stirling numbers of the first kind (unsigned)."""
    if n == 0 and k == 0:
        return 1
    if n == 0 or k == 0:
        return 0
    return (n - 1) * stirling_first(n - 1, k) + stirling_first(n - 1, k - 1)


def stirling_second(n: int, k: int) -> int:
    """Stirling numbers of the second kind."""
    if n == 0 and k == 0:
        return 1
    if n == 0 or k == 0:
        return 0
    return k * stirling_second(n - 1, k) + stirling_second(n - 1, k - 1)


# =============================================================================
# SECTION 7: DIFFERENTIAL EQUATIONS
# =============================================================================

def euler_method(f: Callable[[float, float], float], y0: float,
                 t0: float, t_end: float, h: float) -> List[Tuple[float, float]]:
    """Solve ODE y' = f(t, y) using Euler's method."""
    result = [(t0, y0)]
    t, y = t0, y0

    while t < t_end:
        y = y + h * f(t, y)
        t = t + h
        result.append((t, y))

    return result


def improved_euler_method(f: Callable[[float, float], float], y0: float,
                          t0: float, t_end: float, h: float) -> List[Tuple[float, float]]:
    """Solve ODE using Heun's method (improved Euler)."""
    result = [(t0, y0)]
    t, y = t0, y0

    while t < t_end:
        k1 = f(t, y)
        k2 = f(t + h, y + h * k1)
        y = y + h * (k1 + k2) / 2
        t = t + h
        result.append((t, y))

    return result


def runge_kutta_4(f: Callable[[float, float], float], y0: float,
                  t0: float, t_end: float, h: float) -> List[Tuple[float, float]]:
    """Solve ODE y' = f(t, y) using 4th order Runge-Kutta method."""
    result = [(t0, y0)]
    t, y = t0, y0

    while t < t_end:
        k1 = f(t, y)
        k2 = f(t + h/2, y + h*k1/2)
        k3 = f(t + h/2, y + h*k2/2)
        k4 = f(t + h, y + h*k3)

        y = y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
        t = t + h
        result.append((t, y))

    return result


def runge_kutta_fehlberg(f: Callable[[float, float], float], y0: float,
                         t0: float, t_end: float, tol: float = 1e-6) -> List[Tuple[float, float]]:
    """Adaptive Runge-Kutta-Fehlberg method (RK45)."""
    result = [(t0, y0)]
    t, y = t0, y0
    h = (t_end - t0) / 100  # Initial step size

    while t < t_end:
        k1 = h * f(t, y)
        k2 = h * f(t + h/4, y + k1/4)
        k3 = h * f(t + 3*h/8, y + 3*k1/32 + 9*k2/32)
        k4 = h * f(t + 12*h/13, y + 1932*k1/2197 - 7200*k2/2197 + 7296*k3/2197)
        k5 = h * f(t + h, y + 439*k1/216 - 8*k2 + 3680*k3/513 - 845*k4/4104)
        k6 = h * f(t + h/2, y - 8*k1/27 + 2*k2 - 3544*k3/2565 + 1859*k4/4104 - 11*k5/40)

        y4 = y + 25*k1/216 + 1408*k3/2565 + 2197*k4/4104 - k5/5
        y5 = y + 16*k1/135 + 6656*k3/12825 + 28561*k4/56430 - 9*k5/50 + 2*k6/55

        error = abs(y5 - y4)

        if error < tol:
            t = t + h
            y = y5
            result.append((t, y))

        # Adjust step size
        if error > 0:
            h = 0.9 * h * (tol / error) ** 0.2
        h = min(h, t_end - t)

    return result


def adams_bashforth_4(f: Callable[[float, float], float], y0: float,
                      t0: float, t_end: float, h: float) -> List[Tuple[float, float]]:
    """4-step Adams-Bashforth method for ODEs."""
    # Use RK4 for first 4 points
    initial = runge_kutta_4(f, y0, t0, t0 + 3*h, h)

    result = list(initial)
    t_values = [p[0] for p in result]
    y_values = [p[1] for p in result]
    f_values = [f(t_values[i], y_values[i]) for i in range(4)]

    t = t_values[-1]
    while t < t_end:
        # Adams-Bashforth 4-step formula
        y_new = y_values[-1] + (h/24) * (55*f_values[-1] - 59*f_values[-2] +
                                          37*f_values[-3] - 9*f_values[-4])
        t = t + h

        result.append((t, y_new))
        y_values.append(y_new)
        f_values.append(f(t, y_new))
        f_values.pop(0)
        y_values.pop(0)

    return result


def finite_difference_second_order(y_values: List[float], h: float) -> List[float]:
    """Calculate second derivative using central finite differences."""
    n = len(y_values)
    d2y = [0.0] * n

    for i in range(1, n - 1):
        d2y[i] = (y_values[i + 1] - 2 * y_values[i] + y_values[i - 1]) / (h ** 2)

    # Forward difference for first point
    if n >= 3:
        d2y[0] = (y_values[2] - 2 * y_values[1] + y_values[0]) / (h ** 2)

    # Backward difference for last point
    if n >= 3:
        d2y[-1] = (y_values[-1] - 2 * y_values[-2] + y_values[-3]) / (h ** 2)

    return d2y


# =============================================================================
# SECTION 8: OPTIMIZATION ALGORITHMS
# =============================================================================

def gradient_descent(f: Callable[[List[float]], float],
                     grad_f: Callable[[List[float]], List[float]],
                     x0: List[float], learning_rate: float = 0.01,
                     tol: float = 1e-6, max_iter: int = 10000) -> List[float]:
    """Gradient descent optimization."""
    x = list(x0)

    for _ in range(max_iter):
        grad = grad_f(x)
        x_new = [x[i] - learning_rate * grad[i] for i in range(len(x))]

        if math.sqrt(sum((x_new[i] - x[i]) ** 2 for i in range(len(x)))) < tol:
            return x_new

        x = x_new

    return x


def momentum_gradient_descent(f: Callable[[List[float]], float],
                              grad_f: Callable[[List[float]], List[float]],
                              x0: List[float], learning_rate: float = 0.01,
                              momentum: float = 0.9, tol: float = 1e-6,
                              max_iter: int = 10000) -> List[float]:
    """Gradient descent with momentum."""
    x = list(x0)
    v = [0.0] * len(x)

    for _ in range(max_iter):
        grad = grad_f(x)
        v = [momentum * v[i] - learning_rate * grad[i] for i in range(len(x))]
        x_new = [x[i] + v[i] for i in range(len(x))]

        if math.sqrt(sum((x_new[i] - x[i]) ** 2 for i in range(len(x)))) < tol:
            return x_new

        x = x_new

    return x


def golden_section_search(f: Callable[[float], float], a: float, b: float,
                          tol: float = 1e-6) -> float:
    """Golden section search for finding minimum in [a, b]."""
    phi = (1 + math.sqrt(5)) / 2
    resphi = 2 - phi

    c = b - resphi * (b - a)
    d = a + resphi * (b - a)

    while abs(b - a) > tol:
        if f(c) < f(d):
            b = d
            d = c
            c = b - resphi * (b - a)
        else:
            a = c
            c = d
            d = a + resphi * (b - a)

    return (a + b) / 2


def simulated_annealing(f: Callable[[List[float]], float], x0: List[float],
                        temp: float = 1000, cooling_rate: float = 0.995,
                        min_temp: float = 1e-8,
                        max_iter: int = 10000) -> Tuple[List[float], float]:
    """Simulated annealing optimization."""
    current = list(x0)
    current_energy = f(current)
    best = list(current)
    best_energy = current_energy

    T = temp

    for _ in range(max_iter):
        if T < min_temp:
            break

        # Generate neighbor
        neighbor = [x + random.gauss(0, T) for x in current]
        neighbor_energy = f(neighbor)

        delta = neighbor_energy - current_energy

        if delta < 0 or random.random() < math.exp(-delta / T):
            current = neighbor
            current_energy = neighbor_energy

            if current_energy < best_energy:
                best = list(current)
                best_energy = current_energy

        T *= cooling_rate

    return best, best_energy


def nelder_mead(f: Callable[[List[float]], float], x0: List[float],
                alpha: float = 1, gamma: float = 2, rho: float = 0.5,
                sigma: float = 0.5, tol: float = 1e-6,
                max_iter: int = 1000) -> List[float]:
    """Nelder-Mead simplex optimization algorithm."""
    n = len(x0)

    # Initialize simplex
    simplex = [list(x0)]
    for i in range(n):
        point = list(x0)
        point[i] += 1.0
        simplex.append(point)

    for _ in range(max_iter):
        # Order vertices by function value
        simplex.sort(key=f)

        # Check convergence
        values = [f(v) for v in simplex]
        if max(values) - min(values) < tol:
            break

        # Centroid of all points except worst
        centroid = [sum(simplex[i][j] for i in range(n)) / n for j in range(n)]

        # Reflection
        reflected = [centroid[j] + alpha * (centroid[j] - simplex[-1][j])
                     for j in range(n)]

        if f(simplex[0]) <= f(reflected) < f(simplex[-2]):
            simplex[-1] = reflected
        elif f(reflected) < f(simplex[0]):
            # Expansion
            expanded = [centroid[j] + gamma * (reflected[j] - centroid[j])
                        for j in range(n)]
            simplex[-1] = expanded if f(expanded) < f(reflected) else reflected
        else:
            # Contraction
            contracted = [centroid[j] + rho * (simplex[-1][j] - centroid[j])
                          for j in range(n)]
            if f(contracted) < f(simplex[-1]):
                simplex[-1] = contracted
            else:
                # Shrink
                for i in range(1, n + 1):
                    simplex[i] = [simplex[0][j] + sigma * (simplex[i][j] - simplex[0][j])
                                  for j in range(n)]

    return simplex[0]


def conjugate_gradient(A: Matrix, b: List[float], x0: List[float] = None,
                       tol: float = 1e-10, max_iter: int = 1000) -> List[float]:
    """Conjugate gradient method for solving Ax = b."""
    n = len(b)
    x = x0 if x0 else [0.0] * n

    # r = b - Ax
    Ax = [sum(A.data[i][j] * x[j] for j in range(n)) for i in range(n)]
    r = [b[i] - Ax[i] for i in range(n)]
    p = list(r)

    rs_old = sum(r[i] ** 2 for i in range(n))

    for _ in range(max_iter):
        Ap = [sum(A.data[i][j] * p[j] for j in range(n)) for i in range(n)]
        pAp = sum(p[i] * Ap[i] for i in range(n))

        if abs(pAp) < 1e-15:
            break

        alpha = rs_old / pAp
        x = [x[i] + alpha * p[i] for i in range(n)]
        r = [r[i] - alpha * Ap[i] for i in range(n)]

        rs_new = sum(r[i] ** 2 for i in range(n))

        if math.sqrt(rs_new) < tol:
            break

        p = [r[i] + (rs_new / rs_old) * p[i] for i in range(n)]
        rs_old = rs_new

    return x


# =============================================================================
# SECTION 9: FOURIER ANALYSIS
# =============================================================================

def dft(x: List[complex]) -> List[complex]:
    """Discrete Fourier Transform (naive O(n^2) implementation)."""
    N = len(x)
    return [sum(x[n] * (math.cos(2 * math.pi * k * n / N) -
                        1j * math.sin(2 * math.pi * k * n / N))
                for n in range(N)) for k in range(N)]


def idft(X: List[complex]) -> List[complex]:
    """Inverse Discrete Fourier Transform."""
    N = len(X)
    return [sum(X[k] * (math.cos(2 * math.pi * k * n / N) +
                        1j * math.sin(2 * math.pi * k * n / N))
                for k in range(N)) / N for n in range(N)]


def fft(x: List[complex]) -> List[complex]:
    """Fast Fourier Transform using Cooley-Tukey algorithm."""
    N = len(x)

    if N <= 1:
        return x

    if N & (N - 1) != 0:
        # Pad to next power of 2
        next_pow2 = 1 << (N - 1).bit_length()
        x = list(x) + [0] * (next_pow2 - N)
        N = next_pow2

    if N <= 1:
        return x

    # Divide
    even = fft(x[0::2])
    odd = fft(x[1::2])

    # Conquer
    T = [math.e ** (-2j * math.pi * k / N) * odd[k] for k in range(N // 2)]

    return [even[k] + T[k] for k in range(N // 2)] + \
           [even[k] - T[k] for k in range(N // 2)]


def ifft(X: List[complex]) -> List[complex]:
    """Inverse Fast Fourier Transform."""
    N = len(X)
    # Conjugate, apply FFT, conjugate again, and scale
    X_conj = [complex(x.real, -x.imag) for x in X]
    result = fft(X_conj)
    return [complex(x.real / N, -x.imag / N) for x in result]


def power_spectrum(x: List[float]) -> List[float]:
    """Calculate power spectrum of a signal."""
    X = fft([complex(xi) for xi in x])
    return [abs(Xi) ** 2 for Xi in X]


def autocorrelation(x: List[float]) -> List[float]:
    """Calculate autocorrelation using FFT."""
    N = len(x)
    # Pad to avoid circular correlation
    padded = x + [0] * N

    # FFT of padded signal
    X = fft([complex(xi) for xi in padded])

    # Power spectrum
    S = [Xi * Xi.conjugate() for Xi in X]

    # Inverse FFT
    result = ifft(S)

    # Return real part, normalized
    return [result[i].real / N for i in range(N)]


def cross_correlation(x: List[float], y: List[float]) -> List[float]:
    """Calculate cross-correlation of two signals."""
    N = max(len(x), len(y))
    # Pad both signals
    x_padded = x + [0] * (2 * N - len(x))
    y_padded = y + [0] * (2 * N - len(y))

    X = fft([complex(xi) for xi in x_padded])
    Y = fft([complex(yi) for yi in y_padded])

    # Cross-spectrum (conjugate of Y)
    S = [X[i] * complex(Y[i].real, -Y[i].imag) for i in range(len(X))]

    result = ifft(S)
    return [r.real for r in result]


# =============================================================================
# SECTION 10: POLYNOMIAL OPERATIONS
# =============================================================================

class Polynomial:
    """Class for polynomial operations."""

    def __init__(self, coefficients: List[float]):
        """coefficients[i] is the coefficient of x^i."""
        self.coeffs = list(coefficients)
        self._normalize()

    def _normalize(self):
        """Remove trailing zeros."""
        while len(self.coeffs) > 1 and self.coeffs[-1] == 0:
            self.coeffs.pop()

    @property
    def degree(self) -> int:
        return len(self.coeffs) - 1

    def __repr__(self) -> str:
        terms = []
        for i, c in enumerate(self.coeffs):
            if c != 0:
                if i == 0:
                    terms.append(f"{c}")
                elif i == 1:
                    terms.append(f"{c}x")
                else:
                    terms.append(f"{c}x^{i}")
        return " + ".join(terms) if terms else "0"

    def __call__(self, x: float) -> float:
        """Evaluate polynomial at x using Horner's method."""
        result = 0
        for c in reversed(self.coeffs):
            result = result * x + c
        return result

    def __add__(self, other: 'Polynomial') -> 'Polynomial':
        max_len = max(len(self.coeffs), len(other.coeffs))
        result = [0.0] * max_len
        for i, c in enumerate(self.coeffs):
            result[i] += c
        for i, c in enumerate(other.coeffs):
            result[i] += c
        return Polynomial(result)

    def __sub__(self, other: 'Polynomial') -> 'Polynomial':
        max_len = max(len(self.coeffs), len(other.coeffs))
        result = [0.0] * max_len
        for i, c in enumerate(self.coeffs):
            result[i] += c
        for i, c in enumerate(other.coeffs):
            result[i] -= c
        return Polynomial(result)

    def __mul__(self, other: 'Polynomial') -> 'Polynomial':
        result = [0.0] * (len(self.coeffs) + len(other.coeffs) - 1)
        for i, c1 in enumerate(self.coeffs):
            for j, c2 in enumerate(other.coeffs):
                result[i + j] += c1 * c2
        return Polynomial(result)

    def derivative(self) -> 'Polynomial':
        """Return the derivative polynomial."""
        if self.degree == 0:
            return Polynomial([0])
        return Polynomial([i * self.coeffs[i] for i in range(1, len(self.coeffs))])

    def integral(self, C: float = 0) -> 'Polynomial':
        """Return the indefinite integral with constant C."""
        result = [C] + [self.coeffs[i] / (i + 1) for i in range(len(self.coeffs))]
        return Polynomial(result)

    def definite_integral(self, a: float, b: float) -> float:
        """Calculate definite integral from a to b."""
        antideriv = self.integral()
        return antideriv(b) - antideriv(a)


def lagrange_interpolation(points: List[Tuple[float, float]]) -> Polynomial:
    """Create interpolating polynomial using Lagrange method."""
    n = len(points)
    result = Polynomial([0])

    for i in range(n):
        xi, yi = points[i]

        # Create basis polynomial
        basis = Polynomial([1])
        for j in range(n):
            if i != j:
                xj = points[j][0]
                # (x - xj) / (xi - xj)
                basis = basis * Polynomial([-xj / (xi - xj), 1 / (xi - xj)])

        result = result + Polynomial([yi]) * basis

    return result


def newton_divided_differences(points: List[Tuple[float, float]]) -> List[float]:
    """Calculate divided differences for Newton interpolation."""
    n = len(points)
    table = [[0.0] * n for _ in range(n)]

    for i in range(n):
        table[i][0] = points[i][1]

    for j in range(1, n):
        for i in range(n - j):
            table[i][j] = (table[i + 1][j - 1] - table[i][j - 1]) / \
                          (points[i + j][0] - points[i][0])

    return [table[0][i] for i in range(n)]


def chebyshev_polynomial(n: int, x: float) -> float:
    """Evaluate Chebyshev polynomial of the first kind T_n(x)."""
    if n == 0:
        return 1.0
    if n == 1:
        return x

    T_prev, T_curr = 1.0, x
    for _ in range(2, n + 1):
        T_next = 2 * x * T_curr - T_prev
        T_prev, T_curr = T_curr, T_next
    return T_curr


def legendre_polynomial(n: int, x: float) -> float:
    """Evaluate Legendre polynomial P_n(x)."""
    if n == 0:
        return 1.0
    if n == 1:
        return x

    P_prev, P_curr = 1.0, x
    for k in range(2, n + 1):
        P_next = ((2 * k - 1) * x * P_curr - (k - 1) * P_prev) / k
        P_prev, P_curr = P_curr, P_next
    return P_curr


# =============================================================================
# SECTION 11: COMPLEX NUMBER OPERATIONS
# =============================================================================

def complex_add(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    """Add two complex numbers represented as tuples (real, imag)."""
    return (a[0] + b[0], a[1] + b[1])


def complex_multiply(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    """Multiply two complex numbers."""
    return (a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0])


def complex_divide(a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    """Divide two complex numbers."""
    denom = b[0] ** 2 + b[1] ** 2
    return ((a[0] * b[0] + a[1] * b[1]) / denom, (a[1] * b[0] - a[0] * b[1]) / denom)


def complex_magnitude(z: Tuple[float, float]) -> float:
    """Calculate magnitude of complex number."""
    return math.sqrt(z[0] ** 2 + z[1] ** 2)


def complex_phase(z: Tuple[float, float]) -> float:
    """Calculate phase (argument) of complex number."""
    return math.atan2(z[1], z[0])


def complex_conjugate(z: Tuple[float, float]) -> Tuple[float, float]:
    """Return complex conjugate."""
    return (z[0], -z[1])


def complex_power(z: Tuple[float, float], n: int) -> Tuple[float, float]:
    """Calculate z^n using De Moivre's theorem."""
    r = complex_magnitude(z)
    theta = complex_phase(z)

    r_n = r ** n
    theta_n = n * theta

    return (r_n * math.cos(theta_n), r_n * math.sin(theta_n))


def complex_roots(z: Tuple[float, float], n: int) -> List[Tuple[float, float]]:
    """Calculate all n-th roots of z."""
    r = complex_magnitude(z)
    theta = complex_phase(z)

    r_n = r ** (1 / n)
    roots = []

    for k in range(n):
        theta_k = (theta + 2 * math.pi * k) / n
        roots.append((r_n * math.cos(theta_k), r_n * math.sin(theta_k)))

    return roots


def complex_exp(z: Tuple[float, float]) -> Tuple[float, float]:
    """Calculate e^z for complex z."""
    r = math.exp(z[0])
    return (r * math.cos(z[1]), r * math.sin(z[1]))


def complex_log(z: Tuple[float, float]) -> Tuple[float, float]:
    """Calculate principal value of log(z)."""
    return (math.log(complex_magnitude(z)), complex_phase(z))


def mandelbrot_iterate(c: Tuple[float, float], max_iter: int = 100) -> int:
    """Return number of iterations before escaping for Mandelbrot set."""
    z = (0.0, 0.0)

    for i in range(max_iter):
        if complex_magnitude(z) > 2:
            return i
        z = complex_add(complex_multiply(z, z), c)

    return max_iter


def julia_iterate(z: Tuple[float, float], c: Tuple[float, float], max_iter: int = 100) -> int:
    """Return number of iterations before escaping for Julia set."""
    for i in range(max_iter):
        if complex_magnitude(z) > 2:
            return i
        z = complex_add(complex_multiply(z, z), c)
    return max_iter


# =============================================================================
# SECTION 12: GRAPH ALGORITHMS (Mathematical)
# =============================================================================

def dijkstra(graph: Dict[int, List[Tuple[int, float]]], start: int) -> Dict[int, float]:
    """Dijkstra's algorithm for shortest paths."""
    distances = {start: 0}
    visited = set()

    # Priority queue simulation
    to_visit = [(0, start)]

    while to_visit:
        to_visit.sort(reverse=True)
        current_dist, current = to_visit.pop()

        if current in visited:
            continue

        visited.add(current)

        for neighbor, weight in graph.get(current, []):
            distance = current_dist + weight
            if neighbor not in distances or distance < distances[neighbor]:
                distances[neighbor] = distance
                to_visit.append((distance, neighbor))

    return distances


def floyd_warshall(n: int, edges: List[Tuple[int, int, float]]) -> List[List[float]]:
    """Floyd-Warshall algorithm for all-pairs shortest paths."""
    INF = float('inf')
    dist = [[INF] * n for _ in range(n)]

    for i in range(n):
        dist[i][i] = 0

    for u, v, w in edges:
        dist[u][v] = w

    for k in range(n):
        for i in range(n):
            for j in range(n):
                if dist[i][k] + dist[k][j] < dist[i][j]:
                    dist[i][j] = dist[i][k] + dist[k][j]

    return dist


def topological_sort(graph: Dict[int, List[int]]) -> List[int]:
    """Topological sort using Kahn's algorithm."""
    in_degree = defaultdict(int)

    for node in graph:
        for neighbor in graph[node]:
            in_degree[neighbor] += 1

    queue = [node for node in graph if in_degree[node] == 0]
    result = []

    while queue:
        node = queue.pop(0)
        result.append(node)

        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result if len(result) == len(graph) else []


def bellman_ford(n: int, edges: List[Tuple[int, int, float]], start: int) -> Optional[List[float]]:
    """Bellman-Ford algorithm for single-source shortest paths with negative edges."""
    INF = float('inf')
    dist = [INF] * n
    dist[start] = 0

    for _ in range(n - 1):
        for u, v, w in edges:
            if dist[u] != INF and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w

    # Check for negative cycles
    for u, v, w in edges:
        if dist[u] != INF and dist[u] + w < dist[v]:
            return None  # Negative cycle detected

    return dist


# =============================================================================
# SECTION 13: NUMERICAL UTILITIES
# =============================================================================

def numerical_derivative(f: Callable[[float], float], x: float, h: float = 1e-5) -> float:
    """Calculate numerical derivative using central difference."""
    return (f(x + h) - f(x - h)) / (2 * h)


def numerical_second_derivative(f: Callable[[float], float], x: float, h: float = 1e-5) -> float:
    """Calculate numerical second derivative."""
    return (f(x + h) - 2 * f(x) + f(x - h)) / (h ** 2)


def numerical_gradient(f: Callable[[List[float]], float], x: List[float],
                       h: float = 1e-5) -> List[float]:
    """Calculate numerical gradient."""
    grad = []
    for i in range(len(x)):
        x_plus = list(x)
        x_minus = list(x)
        x_plus[i] += h
        x_minus[i] -= h
        grad.append((f(x_plus) - f(x_minus)) / (2 * h))
    return grad


def numerical_hessian(f: Callable[[List[float]], float], x: List[float],
                      h: float = 1e-4) -> List[List[float]]:
    """Calculate numerical Hessian matrix."""
    n = len(x)
    hess = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            x_pp = list(x)
            x_pm = list(x)
            x_mp = list(x)
            x_mm = list(x)

            x_pp[i] += h
            x_pp[j] += h
            x_pm[i] += h
            x_pm[j] -= h
            x_mp[i] -= h
            x_mp[j] += h
            x_mm[i] -= h
            x_mm[j] -= h

            hess[i][j] = (f(x_pp) - f(x_pm) - f(x_mp) + f(x_mm)) / (4 * h ** 2)

    return hess


def chebyshev_nodes(n: int, a: float = -1, b: float = 1) -> List[float]:
    """Generate n Chebyshev nodes in [a, b]."""
    nodes = [math.cos((2 * k - 1) * math.pi / (2 * n)) for k in range(1, n + 1)]
    # Transform from [-1, 1] to [a, b]
    return [(node + 1) * (b - a) / 2 + a for node in nodes]


def cubic_spline_coefficients(x: List[float], y: List[float]) -> List[Tuple[float, float, float, float]]:
    """Calculate cubic spline coefficients for natural cubic spline."""
    n = len(x) - 1
    h = [x[i + 1] - x[i] for i in range(n)]

    # Set up tridiagonal system
    alpha = [3 * (y[i + 1] - y[i]) / h[i] - 3 * (y[i] - y[i - 1]) / h[i - 1]
             for i in range(1, n)]

    # Solve for c coefficients (natural spline: c[0] = c[n] = 0)
    l = [1.0] + [0.0] * n
    mu = [0.0] * (n + 1)
    z = [0.0] * (n + 1)

    for i in range(1, n):
        l[i] = 2 * (x[i + 1] - x[i - 1]) - h[i - 1] * mu[i - 1]
        mu[i] = h[i] / l[i]
        z[i] = (alpha[i - 1] - h[i - 1] * z[i - 1]) / l[i]

    l[n] = 1.0
    z[n] = 0.0

    c = [0.0] * (n + 1)
    b = [0.0] * n
    d = [0.0] * n

    for j in range(n - 1, -1, -1):
        c[j] = z[j] - mu[j] * c[j + 1]
        b[j] = (y[j + 1] - y[j]) / h[j] - h[j] * (c[j + 1] + 2 * c[j]) / 3
        d[j] = (c[j + 1] - c[j]) / (3 * h[j])

    return [(y[i], b[i], c[i], d[i]) for i in range(n)]


# =============================================================================
# MAIN DEMONSTRATION
# =============================================================================

def demonstrate_calculations():
    """Demonstrate all the calculation functions."""
    print("=" * 80)
    print("COMPLEX CALCULATIONS DEMONSTRATION")
    print("=" * 80)

    # Prime numbers
    print("\n--- PRIME NUMBERS ---")
    primes = sieve_of_eratosthenes(100)
    print(f"Primes up to 100: {primes}")
    print(f"Prime factorization of 360: {prime_factorization(360)}")
    print(f"Goldbach partition of 100: {goldbach_partition(100)}")
    print(f"Miller-Rabin test for 997: {miller_rabin_primality(997)}")
    print(f"Twin primes up to 50: {twin_primes(50)}")

    # Matrix operations
    print("\n--- MATRIX OPERATIONS ---")
    A = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 10]])
    print(f"Matrix A:\n{A}")
    print(f"Determinant: {A.determinant():.4f}")
    print(f"Trace: {A.trace()}")
    print(f"Frobenius norm: {A.frobenius_norm():.4f}")
    print(f"Rank: {A.rank()}")

    B = Matrix([[2, 0, 1], [0, 1, 0], [1, 0, 2]])
    L, U = lu_decomposition(B)
    print(f"\nLU Decomposition of B:")
    print(f"L:\n{L}")
    print(f"U:\n{U}")

    eigenvalue, eigenvector = power_iteration(B)
    print(f"\nDominant eigenvalue: {eigenvalue:.4f}")

    # Numerical integration
    print("\n--- NUMERICAL INTEGRATION ---")
    f = lambda x: math.sin(x)
    print(f"Integration of sin(x) from 0 to π:")
    print(f"  Trapezoidal (n=100): {trapezoidal_rule(f, 0, math.pi, 100):.6f}")
    print(f"  Simpson's (n=100): {simpsons_rule(f, 0, math.pi, 100):.6f}")
    print(f"  Romberg: {romberg_integration(f, 0, math.pi):.6f}")
    print(f"  Gaussian quadrature: {gaussian_quadrature(f, 0, math.pi):.6f}")
    print(f"  Adaptive quadrature: {adaptive_quadrature(f, 0, math.pi):.6f}")
    print(f"  Exact value: {2.0:.6f}")

    # Root finding
    print("\n--- ROOT FINDING ---")
    f = lambda x: x**3 - x - 2
    df = lambda x: 3*x**2 - 1
    print(f"Finding root of x³ - x - 2 = 0:")
    print(f"  Bisection: {bisection_method(f, 1, 2):.6f}")
    print(f"  Newton-Raphson: {newton_raphson(f, df, 1.5):.6f}")
    print(f"  Secant: {secant_method(f, 1, 2):.6f}")
    print(f"  Brent: {brent_method(f, 1, 2):.6f}")
    print(f"  Regula Falsi: {regula_falsi(f, 1, 2):.6f}")

    # Statistics
    print("\n--- STATISTICS ---")
    data = [random.gauss(100, 15) for _ in range(1000)]
    print(f"Sample statistics (n=1000, μ=100, σ=15):")
    print(f"  Arithmetic Mean: {mean(data):.2f}")
    print(f"  Geometric Mean: {geometric_mean([abs(x) for x in data]):.2f}")
    print(f"  Median: {median(data):.2f}")
    print(f"  Std Dev: {standard_deviation(data):.2f}")
    print(f"  Skewness: {skewness(data):.4f}")
    print(f"  Kurtosis: {kurtosis(data):.4f}")
    q1, q2, q3 = quartiles(data)
    print(f"  Quartiles: Q1={q1:.2f}, Q2={q2:.2f}, Q3={q3:.2f}")

    # Linear regression
    x = list(range(1, 11))
    y = [2*xi + 1 + random.gauss(0, 0.5) for xi in x]
    slope, intercept, r_sq = linear_regression(x, y)
    print(f"\nLinear regression (y ≈ 2x + 1):")
    print(f"  Slope: {slope:.4f}, Intercept: {intercept:.4f}, R²: {r_sq:.4f}")

    # Special functions
    print("\n--- SPECIAL FUNCTIONS ---")
    print(f"Gamma(5) = {gamma_function(5):.6f} (exact: 24)")
    print(f"Gamma(0.5) = {gamma_function(0.5):.6f} (exact: √π ≈ 1.7725)")
    print(f"Beta(2, 3) = {beta_function(2, 3):.6f}")
    print(f"Fibonacci(20) = {fibonacci(20)}")
    print(f"Catalan(5) = {catalan_number(5)}")
    print(f"GCD(48, 18) = {gcd(48, 18)}")
    print(f"LCM(48, 18) = {lcm(48, 18)}")

    # Differential equations
    print("\n--- DIFFERENTIAL EQUATIONS ---")
    # Solve y' = y, y(0) = 1 (solution: e^t)
    f_ode = lambda t, y: y
    solutions_rk4 = runge_kutta_4(f_ode, 1, 0, 1, 0.1)
    print(f"Solving y' = y, y(0) = 1 using RK4:")
    print(f"  y(1) ≈ {solutions_rk4[-1][1]:.6f} (exact: e ≈ {math.e:.6f})")

    # Optimization
    print("\n--- OPTIMIZATION ---")
    rosenbrock = lambda x: (1 - x[0])**2 + 100*(x[1] - x[0]**2)**2
    result = nelder_mead(rosenbrock, [0, 0])
    print(f"Minimizing Rosenbrock function:")
    print(f"  Nelder-Mead: x = [{result[0]:.6f}, {result[1]:.6f}]")
    print(f"  f(x) = {rosenbrock(result):.6f}")

    # Golden section
    g = lambda x: (x - 2)**2
    x_min = golden_section_search(g, 0, 5)
    print(f"\nGolden section search for (x-2)²:")
    print(f"  Minimum at x = {x_min:.6f}")

    # Fourier
    print("\n--- FOURIER ANALYSIS ---")
    signal = [math.sin(2 * math.pi * k / 16) for k in range(16)]
    spectrum = power_spectrum(signal)
    print(f"Power spectrum of sine wave (peak at k=1):")
    print(f"  Max power at index: {spectrum.index(max(spectrum))}")

    # Polynomial
    print("\n--- POLYNOMIAL OPERATIONS ---")
    p1 = Polynomial([1, 2, 1])  # 1 + 2x + x²
    p2 = Polynomial([1, 1])     # 1 + x
    print(f"p1 = {p1}")
    print(f"p2 = {p2}")
    print(f"p1 * p2 = {p1 * p2}")
    print(f"p1(2) = {p1(2)}")
    print(f"Derivative of p1: {p1.derivative()}")
    print(f"Integral of p1: {p1.integral()}")

    # Complex numbers
    print("\n--- COMPLEX NUMBERS ---")
    z1 = (3, 4)
    print(f"z = 3 + 4i")
    print(f"  |z| = {complex_magnitude(z1):.4f}")
    print(f"  arg(z) = {complex_phase(z1):.4f} radians")
    print(f"  z² = {complex_power(z1, 2)}")
    roots = complex_roots((1, 0), 4)
    print(f"  4th roots of unity: {[(round(r, 4), round(i, 4)) for r, i in roots]}")

    # Mandelbrot
    print(f"\nMandelbrot iterations for c = -0.5 + 0.5i: {mandelbrot_iterate((-0.5, 0.5))}")

    # Graph algorithms
    print("\n--- GRAPH ALGORITHMS ---")
    graph = {
        0: [(1, 4), (2, 1)],
        1: [(3, 1)],
        2: [(1, 2), (3, 5)],
        3: []
    }
    distances = dijkstra(graph, 0)
    print(f"Dijkstra's shortest paths from node 0: {distances}")

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    random.seed(42)  # For reproducibility
    demonstrate_calculations()
