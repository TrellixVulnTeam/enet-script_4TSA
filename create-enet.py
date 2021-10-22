import hls4ml
import tensorflow as tf
import tensorflow_datasets as tfds
import yaml
from keras.models import load_model
import numpy as np

from hls4ml.model.profiling import optimize_fifos_depth
import argparse

classes = {
    7: 1,  # road
    26: 2,  # car
    24: 3  # person
}
# fmt: on

N_CLASSES = len(classes.keys()) + 1
WIDTH = 152
HEIGHT = 240
CROP_FRAC = 0.05
BOX_FRAC = 0.8


def preproc(data):
    # box_starts = [[CROP_FRAC, CROP_FRAC, 1.0 - CROP_FRAC, 1.0 - CROP_FRAC]]
    # box_widths = tf.random.uniform(shape=(1, 4), minval=-CROP_FRAC, maxval=CROP_FRAC)
    box_starts = tf.random.uniform(shape=(1, 2), minval=0, maxval=(1.0 - BOX_FRAC))
    boxes = tf.concat([box_starts, box_starts + [[BOX_FRAC, BOX_FRAC]]], axis=-1)
    box_idx = [0]
    # image = tf.image.resize(data["image_left"], (WIDTH, HEIGHT)) / 255.0
    # segmentation = tf.image.resize(data["segmentation_label"], (WIDTH, HEIGHT), method="nearest")
    image = (
            tf.image.crop_and_resize(
                tf.expand_dims(data["image_left"], 0),
                boxes,
                box_idx,
                crop_size=(HEIGHT, WIDTH),
            )
            / 255.0
    )
    segmentation = tf.image.crop_and_resize(
        tf.expand_dims(data["segmentation_label"], 0),
        boxes,
        box_idx,
        crop_size=(HEIGHT, WIDTH),
        method="nearest",
    )
    image = tf.squeeze(image, 0)
    segmentation = tf.squeeze(segmentation, 0)
    segmentation = tf.cast(segmentation, tf.int32)
    output_segmentation = tf.zeros(segmentation.shape, dtype=segmentation.dtype)

    for cs_class, train_class in classes.items():
        output_segmentation = tf.where(
            segmentation == cs_class, train_class, output_segmentation
        )

    # image = tf.transpose(image, [2, 0, 1])
    # segmentation = tf.transpose(segmentation, [2, 0, 1])
    return image, output_segmentation


def create_cityscapes_ds(split, batch_size, path):
    ds = tfds.load(
        "cityscapes", data_dir="tensorflow_datasets", download=True, split=split
    )
    ds = ds.map(preproc, num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.shuffle(100)
    # ds = ds.take(1 * batch_size)
    # ds = ds.repeat(2)
    ds = ds.batch(batch_size)
    ds = ds.prefetch(tf.data.AUTOTUNE)
    # ds = ds.take(1).repeat(1000)
    ds_numpy = tfds.as_numpy(ds)
    total_elements = []
    for elem in ds_numpy:
        total_elements.append(elem[0])
    np.save('tensorflow_datasets/' + path, total_elements)


def read_dataset(path):
    return np.load(path)


def get_model(n_filters=8, quantization=4):
    return load_model(f'models_h5/hom{quantization}_32_{n_filters}_{n_filters}_{n_filters}_{n_filters}_{n_filters}.h5')

def get_model_and_build_hls(n_filters, clock_period, reuse_factor, quantization, default_precision='ap_fixed<8,4>', input_data=None,
                            output_predictions=None):

    keras_model = get_model(n_filters, quantization)

    hls_config = {
        'Model': {
            'Precision': default_precision,
            'ReuseFactor': reuse_factor,
            'Strategy': 'Resource'
        },
        'LayerName': {
            'conv2d_1' : {
                'ConvImplementation': 'Encoded'
            }
        }
    }
    out_dir = 'hls_f{}_clk{}_rf{}_q{}_p'.format(n_filters, clock_period, reuse_factor, quantization)
    hls_model = optimize_fifos_depth(keras_model, output_dir=out_dir, clock_period=clock_period, backend='VivadoAccelerator',
                                     board='zcu102', hls_config=hls_config, input_data_tb=input_data, output_data_tb=output_predictions)
    hls4ml.templates.VivadoAcceleratorBackend.make_bitfile(hls_model)


parser = argparse.ArgumentParser()
parser.add_argument('-rf','--reuse_factor', type=int, help='Reuse factor', required=True)
parser.add_argument('-f','--n_filters', type=int, help='Filter size', required=True)
parser.add_argument('-c','--clock_period', type=int, help='HLS clock latency in ns', required=True)
parser.add_argument('-q','--quantization', type=int, help='Uniform quatization of the model (i.e.: 4, 8)', required=True)
parser.add_argument('-p', '--precision', type=str, help='Precision used by default in the hls model', nargs='?', default='ap_fixed<8,4>')
parser.add_argument('-i', '--input_data', type=str, help='Input .npy file', nargs='?', default=None)
parser.add_argument('-o', '--output_predictions', type=str, help='Output .npy file', nargs='?', default=None)
args = vars(parser.parse_args())

get_model_and_build_hls(n_filters=args.n_filters, clock_period=args.clock_period, 
                        reuse_factor=args.reuse_factor, quantization=args.quantization, precision=args.precision)