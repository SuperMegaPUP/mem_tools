/* membw — компактный STREAM-подобный тест пропускной способности DRAM.
 *
 * Шесть ядер (Read/Write/Copy/Scale/Add/Triad) на pthreads: пять
 * классических из STREAM + чистая запись Write (её в STREAM нет, а
 * деградацию канала видно именно по записи). Каждый поток гребёт
 * непрерывный срез общих массивов double, привязка к CPU round-robin,
 * барьер между итерациями, результат — лучший и средний GB/s по ITERS
 * замеров (первые 2 — прогрев).
 *
 * usage: membw N_THREADS ITERS SIZE_MIB_PER_ARRAY
 * вывод: "<Kernel> <best_GBs> <avg_GBs>" по строке на ядро.
 *
 * Компиляция: cc -O3 -march=native -pthread -o membw membw.c
 * (march=native включает AVX2 streaming-сторы — без них Write/Copy/Triad
 * занижены из-за RFO-трафика)
 */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

enum { READ, WRITE, COPY, SCALE, ADD, TRIAD, NK };
static const char *KN[NK] = {"Read", "Write", "Copy", "Scale", "Add", "Triad"};
/* байт трафика на элемент: Read/Write 1, Copy/Scale 2, Add/Triad 3.
 * Write считается по полезным данным (8 Б/элемент): streaming-сторы не
 * делают RFO-чтений, поэтому трафик DRAM ровно один байт на байт. */
static const double BYTES[NK] = {1, 1, 2, 2, 3, 3};

static double *A, *B, *C;
static const double SCALAR = 3.0;
static size_t N;              /* элементов на массив */
static int NT, ITERS, NCPU;
static pthread_barrier_t bar;
static double g_best[NK], g_sum[NK];
static volatile double g_sink;

static double now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec * 1e-9;
}

#ifdef __AVX2__
#include <immintrin.h>
/* Векторные ядра с streaming-сторами (_mm256_stream_pd): пишут прямо в
 * DRAM, минуя кэш — без лишнего RFO-трафика, как в эталонном STREAM. */
static void vec_kernel(int k, size_t lo, size_t hi, double *acc_out)
{
	__m256d vs = _mm256_set1_pd(SCALAR);
	__m256d v0 = _mm256_setzero_pd(), v1 = _mm256_setzero_pd();
	size_t i = lo;
	double head = 0;
	/* скалярный прогон до 32-байтного (4 double) выравнивания цели */
	while (i < hi && (i & 3)) {
		switch (k) {
		case READ:  head += A[i]; break;
		case WRITE: B[i] = SCALAR; break;
		case COPY:  B[i] = A[i]; break;
		case SCALE: B[i] = SCALAR * A[i]; break;
		case ADD:   C[i] = A[i] + B[i]; break;
		case TRIAD: C[i] = A[i] + SCALAR * B[i]; break;
		}
		i++;
	}
	for (; i + 8 <= hi; i += 8) {
		switch (k) {
		case READ:
			v0 = _mm256_add_pd(v0, _mm256_loadu_pd(A + i));
			v1 = _mm256_add_pd(v1, _mm256_loadu_pd(A + i + 4));
			break;
		case WRITE:
			_mm256_stream_pd(B + i, vs);
			_mm256_stream_pd(B + i + 4, vs);
			break;
		case COPY:
			_mm256_stream_pd(B + i, _mm256_loadu_pd(A + i));
			_mm256_stream_pd(B + i + 4, _mm256_loadu_pd(A + i + 4));
			break;
		case SCALE:
			_mm256_stream_pd(B + i,
				_mm256_mul_pd(vs, _mm256_loadu_pd(A + i)));
			_mm256_stream_pd(B + i + 4,
				_mm256_mul_pd(vs, _mm256_loadu_pd(A + i + 4)));
			break;
		case ADD:
			_mm256_stream_pd(C + i,
				_mm256_add_pd(_mm256_loadu_pd(A + i),
					      _mm256_loadu_pd(B + i)));
			_mm256_stream_pd(C + i + 4,
				_mm256_add_pd(_mm256_loadu_pd(A + i + 4),
					      _mm256_loadu_pd(B + i + 4)));
			break;
		case TRIAD:
			_mm256_stream_pd(C + i,
				_mm256_add_pd(_mm256_loadu_pd(A + i),
					_mm256_mul_pd(vs, _mm256_loadu_pd(B + i))));
			_mm256_stream_pd(C + i + 4,
				_mm256_add_pd(_mm256_loadu_pd(A + i + 4),
					_mm256_mul_pd(vs, _mm256_loadu_pd(B + i + 4))));
			break;
		}
	}
	double tail = 0;
	for (; i < hi; i++) {	/* хвост <8 элементов */
		switch (k) {
		case READ:  tail += A[i]; break;
		case WRITE: B[i] = SCALAR; break;
		case COPY:  B[i] = A[i]; break;
		case SCALE: B[i] = SCALAR * A[i]; break;
		case ADD:   C[i] = A[i] + B[i]; break;
		case TRIAD: C[i] = A[i] + SCALAR * B[i]; break;
		}
	}
	double s[8];
	_mm256_storeu_pd(s, _mm256_add_pd(v0, v1));
	*acc_out = s[0] + s[1] + s[2] + s[3] + tail + head;
}
#endif

static void *worker(void *arg)
{
	long id = (long)arg;
	size_t lo = N * (size_t)id / (size_t)NT;
	size_t hi = N * (size_t)(id + 1) / (size_t)NT;
	double sink = 0, acc;

	if (NCPU > 0) {
		cpu_set_t cs;
		CPU_ZERO(&cs);
		CPU_SET((int)(id % NCPU), &cs);
		pthread_setaffinity_np(pthread_self(), sizeof cs, &cs);
	}

	for (int k = 0; k < NK; k++) {
		for (int it = 0; it < ITERS + 2; it++) {
			pthread_barrier_wait(&bar);
			double t0 = (id == 0) ? now() : 0;
			acc = 0;
#ifdef __AVX2__
			vec_kernel(k, lo, hi, &acc);
#else
			switch (k) {
			case READ:
				for (size_t i = lo; i < hi; i++)
					acc += A[i];
				break;
			case WRITE:
				for (size_t i = lo; i < hi; i++)
					B[i] = SCALAR;
				break;
			case COPY:
				for (size_t i = lo; i < hi; i++)
					B[i] = A[i];
				break;
			case SCALE:
				for (size_t i = lo; i < hi; i++)
					B[i] = SCALAR * A[i];
				break;
			case ADD:
				for (size_t i = lo; i < hi; i++)
					C[i] = A[i] + B[i];
				break;
			case TRIAD:
				for (size_t i = lo; i < hi; i++)
					C[i] = A[i] + SCALAR * B[i];
				break;
			}
#endif
			sink += acc;
			pthread_barrier_wait(&bar);
			if (id == 0 && it >= 2) {
				double gbs = BYTES[k] * 8.0 * (double)N /
					     (now() - t0) / 1e9;
				if (gbs > g_best[k])
					g_best[k] = gbs;
				g_sum[k] += gbs;
			}
		}
	}
	g_sink += sink;
	return NULL;
}

int main(int argc, char **argv)
{
	if (argc < 4) {
		fprintf(stderr, "usage: %s threads iters size_mib_per_array\n",
			argv[0]);
		return 2;
	}
	NT = atoi(argv[1]);
	ITERS = atoi(argv[2]);
	size_t mib = strtoull(argv[3], NULL, 10);
	if (NT < 1 || ITERS < 1 || mib < 8) {
		fprintf(stderr, "bad args\n");
		return 2;
	}
	N = mib * 1024 * 1024 / 8;
	NCPU = (int)sysconf(_SC_NPROCESSORS_ONLN);

	A = aligned_alloc(64, N * 8);
	B = aligned_alloc(64, N * 8);
	C = aligned_alloc(64, N * 8);
	if (!A || !B || !C) {
		fprintf(stderr, "alloc %zu MiB x3 failed\n", mib);
		return 1;
	}
	for (size_t i = 0; i < N; i++) {
		A[i] = 1.0;
		B[i] = 2.0;
		C[i] = 0.0;
	}

	pthread_barrier_init(&bar, NULL, NT);
	pthread_t *th = calloc(NT, sizeof *th);
	for (long i = 0; i < NT; i++)
		pthread_create(&th[i], NULL, worker, (void *)i);
	for (int i = 0; i < NT; i++)
		pthread_join(th[i], NULL);

	for (int k = 0; k < NK; k++)
		printf("%s %.2f %.2f\n", KN[k], g_best[k], g_sum[k] / ITERS);
	return 0;
}
