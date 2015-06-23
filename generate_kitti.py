"""
Generates input and output numpy data for both train and test set, given
path to dataset.
Data is pickled in OUT_PATH folder, in .bin files.
"""
import theano
import numpy as np
import logging
import random
import sys
import pylab
import multiprocessing as mp

from preprocessing.transform_in import yuv_laplacian_norm, resize
from preprocessing.transform_out import process_out
from preprocessing.class_counter import ClassCounter
from dataset.loader_kitti import load_dataset
from util import try_pickle_dump

logger = logging.getLogger(__name__)

DATASET_PATH = './data/kitti/'
OUT_PATH = './data/kitti/theano_datasets/'
# requested_shape = (188, 620)
requested_shape = (192, 608)


def save_result_img(result_list, result):
    i, layers = result
    for j, layer in enumerate(layers):
        result_list[j][i, :, :, :] = layer


def gen_layers_for_image(i, img):
    img = resize(img[:, :, :], requested_shape)

    rgb_img = img[:, :, 0:3]
    depth_img = img[:, :, 3]
    rgb_imgs = yuv_laplacian_norm(rgb_img, requested_shape, n_layers=3)

    new_imgs = []
    for img in rgb_imgs:
        shp = (img.shape[1], img.shape[2])
        new_img = np.concatenate(
            (img, resize(depth_img, shp).reshape((1, shp[0], shp[1]))), axis=0)
        new_imgs.append(new_img)
    return i, new_imgs


def generate_x(samples, n_layers, gen_func):
    """
    Generates list of processed images in a form of a 2d numpy array.

    samples: list
        list of Sample objects
    n_layers: int
        number of layers
    gen_func: function
        function for generating layers (of images)

    Returns: list of numpy arrays
    """
    # list of numpy array, every for one pyramid layer
    x_list = []
    for i in range(n_layers):
        curr_img_shp = (requested_shape[0] / (2**i),
                        requested_shape[1] / (2**i))
        layer_shp = (len(samples), samples[0].image.shape[2],
                     curr_img_shp[0], curr_img_shp[1])
        logger.info("Layer %d has shape %s", i, layer_shp)
        x_list.append(np.zeros(layer_shp, dtype=theano.config.floatX))

    cpu_count = mp.cpu_count()
    # pool = mp.Pool(cpu_count)
    logger.info("Cpu count %d", cpu_count)

    result_func = lambda result: save_result_img(x_list, result)

    for i, sample in enumerate(samples):
        result_func(gen_func(i, sample.image))
        # pool.apply_async(gen_func, args=(i, sample.image,),
        #                  callback=result_func)
    # pool.close()
    # pool.join()

    return x_list


def save_result_segm(result_list, result):
    """ Callback function, called in main process, saves result """
    i, img = result
    result_list[i] = img


def mark_image(i, img, cc, requested_shape):
    logger.info("Marking image %d", i)
    img = resize(img, requested_shape, inter=0)
    assert(img.shape[:2] == requested_shape)
    layers = process_out(img, cc, requested_shape)
    return i, layers


def generate_targets(samples, class_counter):
    """
    Generates array of segmented images.

    samples: list
        list of Sample objects
    class_counter: ClassCounter object
        object used for generating class markings (class ordinal numbers)

    returns: np.array
        array of class ordinal numbers
    """
    y_shape = (len(samples), requested_shape[0], requested_shape[1])

    y = np.zeros(y_shape, dtype='int8')

    logger.info("Segmented images new shape %s", y.shape)

    # pool = mp.Pool(mp.cpu_count())
    logger.info("Cpu count %d", mp.cpu_count())

    result_func = lambda result: save_result_segm(y, result)

    for i, sample in enumerate(samples):
        result_func(mark_image(i, sample.marked_image,
                               class_counter, requested_shape))
    '''
        pool.apply_async(mark_image,
                         args=(i, sample.marked_image,
                               class_counter, requested_shape,),
                         callback=result_func)
    pool.close()
    pool.join()
    '''

    return y


def split_samples(samples, test_size):
    n = len(samples)
    n_test = int(test_size * n)
    n_train = n - n_test
    logger.info("Splitting dataset, train/test/total, %d/%d/%d"
                % (n_train, n_test, n))

    train_samples = []
    test_samples = []

    for i in xrange(n):
        if i < n_train:
            train_samples.append(samples[i])
        else:
            test_samples.append(samples[i])

    assert(len(train_samples) == n_train)
    assert(len(test_samples) == n_test)

    return train_samples, test_samples


def write_samples_log(samples, outpath):
    with open(outpath, 'w') as f:
        f.writelines("\n".join([s.name for s in samples]))


def main(gen_func, n_layers, show=False):
    logger.info("... loading data")
    logger.debug("Theano.config.floatX is %s" % theano.config.floatX)

    #   samples is list of Sample objects
    samples = load_dataset(DATASET_PATH)
    samples = list(samples)

    #   use only subset of data TODO remove this
    # DATA_TO_USE = 30
    # samples = samples[:DATA_TO_USE]

    random.seed(23454)
    random.shuffle(samples)

    train_samples, test_samples = split_samples(samples, 0.1)
    del samples

    write_samples_log(train_samples, "kitti_samples_train.log")
    write_samples_log(test_samples, "kitti_samples_test.log")

    cc = ClassCounter()

    x_train = generate_x(train_samples, n_layers, gen_func)
    x_test = generate_x(test_samples, n_layers, gen_func)
    y_train = generate_targets(train_samples, cc)
    y_test = generate_targets(test_samples, cc)
    del train_samples
    del test_samples

    cc.log_stats()

    try_pickle_dump(x_train, OUT_PATH + "x_train.bin")
    try_pickle_dump(x_test, OUT_PATH + "x_test.bin")
    try_pickle_dump(y_train, OUT_PATH + "y_train.bin")
    try_pickle_dump(y_test, OUT_PATH + "y_test.bin")

    # print x_train[0][0, 0, 80:90, 80:90]
    # print x_test[0][0, 0, 80:90, 80:90]

    if show:
        n_imgs = 5
        for j in xrange(n_imgs):
            pylab.subplot(3, n_imgs, 0 * n_imgs + j + 1)
            pylab.axis('off')
            pylab.imshow(x_train[0][j, 0, :, :])  # Y
        for j in xrange(n_imgs):
            pylab.subplot(3, n_imgs, 1 * n_imgs + j + 1)
            pylab.gray()
            pylab.axis('off')
            pylab.imshow(x_train[0][j, 3, :, :])  # depth
        for j in xrange(n_imgs):
            pylab.subplot(3, n_imgs, 2 * n_imgs + j + 1)
            pylab.gray()
            pylab.axis('off')
            pylab.imshow(y_train[j, :, :])
        pylab.show()


if __name__ == "__main__":
    '''
    python generate_iccv_1l.py [show]
    '''
    logging.basicConfig(level=logging.INFO)

    show = False
    argc = len(sys.argv)
    if argc > 1 and sys.argv[1] != "show":
        print "Wrong arguments"
        exit(1)
    if argc > 1 and sys.argv[1] == "show":
        show = True

    main(gen_layers_for_image, n_layers=3, show=show)