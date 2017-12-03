from __future__ import print_function

import os
from torch.autograd import Variable
import torch.nn.functional as F
os.environ['CUDA_VISIBLE_DEVICES'] = '0'
from transform import *
from Utils import *
from cdimage import *
from torch.utils.data.sampler import RandomSampler
import operator
# --------------------------------------------------------

from net.resnet101 import ResNet101 as Net

use_cuda = True
IDENTIFIER = "resnet"
SEED = 123456
PROJECT_PATH = './project'
CDISCOUNT_HEIGHT = 180
CDISCOUNT_WIDTH = 180
CDISCOUNT_NUM_CLASSES = 5270

csv_dir = './data/'
root_dir = '../output/'
test_data_filename = 'test.csv'
validation_data_filename = 'validation.csv'

def evaluate_average_prob(net, test_loader):
    cnt = 0

    all_image_ids = np.array([])
    all_probs = np.array([]).reshape(0,CDISCOUNT_NUM_CLASSES)

    # for iter, (images, labels, indices) in enumerate(test_loader, 0):
    for iter, (images, image_ids) in enumerate(test_loader, 0):#remove indices for testing
        if cnt > 4:
            break;

        images = Variable(images.type(torch.FloatTensor)).cuda() if use_cuda else Variable(images.type(torch.FloatTensor))
        image_ids = np.array(image_ids)

        logits = net(images)
        probs  = F.softmax(logits)
        probs = probs.cpu().data.numpy() if use_cuda else probs.data.numpy()
        probs.astype(float)

        all_image_ids = np.concatenate((all_image_ids, image_ids), axis=0)
        all_probs = np.concatenate((all_probs, probs), axis=0)

        cnt = cnt + 1

    product_to_prediction_map = product_predict_average_prob(all_image_ids, all_probs)

    return product_to_prediction_map

def ensemble_predict(cur_procuct_probs, num):
    candidates = np.argmax(cur_procuct_probs, axis=1)
    probs_means = np.mean(cur_procuct_probs, axis=0)
    winner_score = 0.0
    winner = None
    for candidate in candidates:
        # Adopt pre chosen criteria to abandan some instances
        candidate_score = probs_means[candidate] * num
        abandan_cnt = 0
        for probs in cur_procuct_probs:  # iterate each product instance
            if probs[candidate] < probs_means[candidate] - 0.2:
                # abandan this instance
                candidate_score -= probs[candidate]
                abandan_cnt += 1

        if candidate_score > winner_score:
            winner = candidate
            winner_score = candidate_score

    return winner

def TTA(images):
    return [images]

def evaluate_sequential_ensemble(net, test_loader, path):
    cnt = 0
    product_to_prediction_map = {}
    cur_procuct_probs = np.array([]).reshape(0,CDISCOUNT_NUM_CLASSES)
    cur_product_id = None
    transform_num = 1

    with open(path, "a") as file:
        file.write("_id,category_id\n")

        for iter, (images, image_ids) in enumerate(test_loader, 0):
            if cnt > 4:
                break;

            # images = Variable(images.type(torch.FloatTensor)).cuda() if use_cuda else Variable(images.type(torch.FloatTensor))
            image_ids = np.array(image_ids)

            # transforms
            images_list = TTA(images) # a list of image batch using different transforms
            probs_list = []
            for images in images_list:
                images = Variable(images.type(torch.FloatTensor)).cuda()
                logits = net(images)
                probs  = ((F.softmax(logits)).cpu().data.numpy()).astype(float)
                probs_list.append(probs)

            start = 0
            end = 0
            for image_id in image_ids:
                product_id = imageid_to_productid(image_id)

                if cur_product_id == None:
                    cur_product_id = product_id

                if product_id != cur_product_id:
                    # a new product
                    print("new product: " + str(product_id))

                    # find winner for previous product
                    num = (end - start) * transform_num # total number of instances for current product
                    ## get probs in range [start, end)
                    for probs in probs_list:
                        np.concatenate((cur_procuct_probs, np.array(probs[start:end])), axis=0)

                    # do predictions
                    winner = ensemble_predict(cur_procuct_probs, num)

                    # save winner
                    product_to_prediction_map[cur_product_id] = winner

                    # update
                    start = end
                    cur_product_id = product_id
                    cur_procuct_probs = np.array([]).reshape(0,CDISCOUNT_NUM_CLASSES)

                end += 1
            cnt += 1

            np.concatenate((cur_procuct_probs, np.array(probs[start:end])), axis=0)

        # find winner for previous product
        num = (end - start) * transform_num  # total number of instances for current product
        ## get probs in range [start, end)
        for probs in probs_list:
            np.concatenate((cur_procuct_probs, probs[start:end]), axis=0)

        # do predictions
        winner = ensemble_predict(cur_procuct_probs, num)

        # save winner
        product_to_prediction_map[cur_product_id] = winner

        for product_id, prediction in product_to_prediction_map.items():
            file.write(str(product_id) + "," + str(prediction) + "\n")

def write_test_result(path, product_to_prediction_map):
    with open(path, "a") as file:
        file.write("_id,category_id\n")

        for product_id, prediction in product_to_prediction_map.items():
            print(product_id)
            print(prediction)
            file.write(str(product_id) + "," + str(prediction) + "\n")

# main #################################################################
if __name__ == '__main__':
    print( '%s: calling main function ... ' % os.path.basename(__file__))

    initial_checkpoint = "../checkpoint/"+ IDENTIFIER + "/latest.pth"
    res_path = "./test_res/" + IDENTIFIER + "_test_TTA.res"
    validation_batch_size = 64

    net = Net(in_shape = (3, CDISCOUNT_HEIGHT, CDISCOUNT_WIDTH), num_classes=CDISCOUNT_NUM_CLASSES)
    if use_cuda: net.cuda()

    if os.path.isfile(initial_checkpoint):
        print("=> loading checkpoint '{}'".format(initial_checkpoint))
        checkpoint = torch.load(initial_checkpoint)
        net.load_state_dict(checkpoint['state_dict'])  # load model weights from the checkpoint
        print("=> loaded checkpoint '{}'".format(initial_checkpoint))
    else:
        print("=> no checkpoint found at '{}'".format(initial_checkpoint))
        exit(0)

    transform_valid = transforms.Compose([transforms.Lambda(lambda x: general_valid_augment(x))])

    test_dataset = CDiscountTestDataset(csv_dir + test_data_filename, root_dir, transform=transform_valid)

    test_loader  = DataLoader(
                        test_dataset,
                        sampler=SequentialSampler(test_dataset),
                        batch_size  = validation_batch_size,
                        drop_last   = False,
                        num_workers = 4,
                        pin_memory  = True)

    product_to_prediction_map = evaluate_sequential_ensemble(net, test_loader, res_path)

    print('\nsucess!')
