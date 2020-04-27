# import pygame
#
# pygame.init()
# res = 500, 500
# screen = pygame.display.set_mode(res,
#                                  pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.RESIZABLE)
#
# while True:
#     pygame.draw.circle(screen, (255,255,255), (res[0] // 2, res[1] // 2), 100)
#     pygame.display.flip()
#     print('loop')
#     for e in pygame.event.get():
#         if e.type == pygame.VIDEORESIZE:
#             res = e.dict['size']
#             screen = pygame.display.set_mode(res, pygame.HWSURFACE |
#                                              pygame.DOUBLEBUF | pygame.RESIZABLE)
#             print("resize")
import pygame
from pygame.locals import *
pygame.init()
screen=pygame.display.set_mode((500,500),HWSURFACE|DOUBLEBUF|RESIZABLE)
pic=pygame.image.load("ex.png") #You need an example picture in the same folder as this file!
screen.blit(pygame.transform.scale(pic,(500,500)),(0,0))
pygame.display.flip()
res = None
res_p = (500,500)
while True:
    screen.fill((0,0,0))
    screen.blit(pygame.transform.scale(pic, res_p), (0, 0))
    pygame.display.flip()
    resize = False
    for event in pygame.event.get():
        if event.type==QUIT: pygame.display.quit()
        elif event.type==VIDEORESIZE:
            res = event.dict['size']
            resize = True
        if not resize and res:
            print('new screen')
            screen = pygame.display.set_mode(res,HWSURFACE|DOUBLEBUF|RESIZABLE)
            res_p = res
            res = None

